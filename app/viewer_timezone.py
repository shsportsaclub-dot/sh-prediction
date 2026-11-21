"""Presentation-only IP country hints. Never use these for access control or deadlines."""
import csv,gzip,io,ipaddress,json,os,pathlib,sqlite3,tempfile,threading
from datetime import datetime,timezone
from urllib.request import Request,urlopen
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError

RELEASE='2026-11'
URL='https://download.db-ip.com/free/dbip-country-lite-'+RELEASE+'.csv.gz'
ATTRIBUTION={'name':'IP Geolocation by DB-IP','url':'https://db-ip.com','license':'CC BY 4.0','release':RELEASE}
COUNTRY_ZONES=json.loads((pathlib.Path(__file__).with_name('country_timezones.json')).read_text())
PHONE_CODES=json.loads((pathlib.Path(__file__).with_name('phone_countries.json')).read_text())


def valid_zone(value):
 if not isinstance(value,str) or len(value)>100:return None
 try:ZoneInfo(value);return value
 except (ValueError,ZoneInfoNotFoundError):return None


def resolve(country=None,phone_code=None,device=None,phone_country=None):
 regions=[region for region,code in PHONE_CODES.items() if code==phone_code]
 region=phone_country if phone_country in regions else (regions[0] if len(regions)==1 else None)
 for cc,source in ((region,'phone_country'),(country,'ip_country')):
  zones=COUNTRY_ZONES.get(cc,[])
  if len(zones)==1 and valid_zone(zones[0]):return {'timezone':zones[0],'source':source,'estimated':True}
 return {'timezone':valid_zone(device),'source':'device' if valid_zone(device) else 'unresolved','estimated':True}


def db_path():
 return pathlib.Path(os.getenv('SH_GEOIP_DB',str(pathlib.Path(os.getenv('SH_PREDICTION_DB','data/prediction.sqlite3')).resolve().parent/'ip_country.sqlite3')))


def build_database(rows,path):
 path=pathlib.Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 fd,tmp=tempfile.mkstemp(prefix='ip-country-',suffix='.sqlite3',dir=path.parent);os.close(fd)
 c=sqlite3.connect(tmp)
 try:
  c.execute('CREATE TABLE ranges(version INTEGER,start TEXT,end TEXT,country TEXT,PRIMARY KEY(version,start)) WITHOUT ROWID')
  count=0
  for row in rows:
   if len(row)!=3:raise ValueError('Invalid country range row')
   a,b=ipaddress.ip_address(row[0]),ipaddress.ip_address(row[1]);cc=row[2]
   if a.version!=b.version or int(a)>int(b) or len(cc)!=2 or not cc.isalpha():raise ValueError('Invalid IP range')
   c.execute('INSERT INTO ranges VALUES(?,?,?,?)',(a.version,f'{int(a):032x}',f'{int(b):032x}',cc.upper()));count+=1
   if count>2000000:raise ValueError('Too many GeoIP rows')
  if not count:raise ValueError('Empty GeoIP archive')
  c.execute('CREATE TABLE metadata(release TEXT,rows INTEGER,source TEXT,license TEXT)')
  c.execute('INSERT INTO metadata VALUES(?,?,?,?)',(RELEASE,count,URL,'CC BY 4.0'));c.commit()
  if c.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Invalid GeoIP database')
  c.close();os.replace(tmp,path);return count
 finally:
  c.close()
  if os.path.exists(tmp):os.unlink(tmp)


def country_for_ip(address,path=None):
 try:
  ip=ipaddress.ip_address(address)
  if not ip.is_global:return None
  path=pathlib.Path(path) if path else db_path()
  if not path.is_file():return None
  c=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=1)
  try:
   key=f'{int(ip):032x}'
   row=c.execute('SELECT end,country FROM ranges WHERE version=? AND start<=? ORDER BY start DESC LIMIT 1',(ip.version,key)).fetchone()
   return row[1] if row and key<=row[0] else None
  finally:c.close()
 except (ValueError,TypeError,OSError,sqlite3.Error):return None


def request_ip(handler):
 # Display hints only. On Render the documented forwarding header is used.
 # Caller-supplied forwarding can affect their display, never credentials/locks.
 candidates=[handler.client_address[0]]
 if os.getenv('RENDER')=='true':
  forwarded=handler.headers.get('X-Forwarded-For','')[:2048]
  if forwarded:candidates=[forwarded.split(',')[0].strip()]
 try:
  ip=ipaddress.ip_address(candidates[0]);return str(ip) if ip.is_global else None
 except ValueError:return None


def prepare_database():
 path=db_path()
 try:
  if path.is_file():
   with sqlite3.connect(path) as c:
    if c.execute('SELECT release FROM metadata').fetchone()[0]==RELEASE:return
  req=Request(URL,headers={'User-Agent':'SH-Prediction-Timezone/1.0'})
  with urlopen(req,timeout=25) as response:
   raw=response.read(16*1024*1024+1)
  if len(raw)>16*1024*1024:raise ValueError('GeoIP download too large')
  with gzip.GzipFile(fileobj=io.BytesIO(raw)) as zipped:
   data=zipped.read(80*1024*1024+1)
  if len(data)>80*1024*1024:raise ValueError('GeoIP data too large')
  n=build_database(csv.reader(io.StringIO(data.decode('utf-8'))),path)
  print('IP timezone country database ready:',n,'rows; release',RELEASE,flush=True)
 except Exception as exc:
  # Existing database remains intact; score acquisition is independent.
  print('IP timezone database unavailable:',type(exc).__name__,flush=True)


def start():
 thread=threading.Thread(target=prepare_database,name='ip-timezone-database',daemon=True);thread.start();return thread
