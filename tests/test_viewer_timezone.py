import sys,pathlib,tempfile,unittest,sqlite3
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'app'))
import viewer_timezone as v

class ViewerTimezoneTests(unittest.TestCase):
 def test_country_and_phone_fallback(self):
  self.assertEqual(v.resolve('IN',None,'Europe/Paris')['timezone'],'Asia/Kolkata')
  self.assertEqual(v.resolve(None,'+880','Europe/Paris')['timezone'],'Asia/Dhaka')
  self.assertEqual(v.resolve(None,'+92','Europe/Paris')['timezone'],'Asia/Karachi')
  self.assertEqual(v.resolve(None,'+33','Asia/Kolkata')['timezone'],'Europe/Paris')
  self.assertEqual(v.resolve('US','+1','America/New_York')['source'],'device')
  self.assertIsNone(v.resolve(None,None,'invalid/zone')['timezone'])
 def test_worldwide_calling_codes_and_shared_code_country(self):
  self.assertEqual(len(v.PHONE_CODES),245)
  self.assertEqual(v.PHONE_CODES['IN'],'+91')
  self.assertEqual(v.PHONE_CODES['PK'],'+92')
  self.assertIsNone(v.resolve(None,'+49',None)['timezone'])  # Berlin/Busingen: no guessed zone
  self.assertEqual(v.resolve(None,'+81',None)['timezone'],'Asia/Tokyo')
  self.assertEqual(v.resolve(None,'+44',None,phone_country='GB')['timezone'],'Europe/London')
  self.assertIsNone(v.resolve(None,'+1',None,phone_country='US')['timezone'])

 def test_local_database_ranges_and_ipv6(self):
  with tempfile.TemporaryDirectory() as d:
   path=pathlib.Path(d)/'geo.sqlite3'
   v.build_database([['1.1.1.0','1.1.1.255','AU'],['8.8.8.0','8.8.8.255','US'],['2001:4860::','2001:4860::ffff','US']],path)
   self.assertEqual(v.country_for_ip('1.1.1.255',path),'AU')
   self.assertIsNone(v.country_for_ip('1.1.2.0',path))
   self.assertEqual(v.country_for_ip('2001:4860::42',path),'US')
   self.assertIsNone(v.country_for_ip('127.0.0.1',path))
   self.assertIsNone(v.country_for_ip('bad',path))
   self.assertIsNone(v.country_for_ip('8.8.8.8',pathlib.Path(d)/'missing'))
 def test_phone_takes_priority_and_ambiguous_phone_does_not_guess(self):
  self.assertEqual(v.resolve('PK','+91','Europe/Paris')['source'],'phone_country')
  self.assertEqual(v.resolve('PK','+91','Europe/Paris')['timezone'],'Asia/Kolkata')
  self.assertIsNone(v.resolve('US','+1',None)['timezone'])
  self.assertEqual(v.resolve('US','+1','America/Los_Angeles')['timezone'],'America/Los_Angeles')
