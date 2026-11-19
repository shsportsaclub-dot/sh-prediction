import unittest
from live_bridge import LiveBridge, event_key

class BridgeTests(unittest.TestCase):
    def test_dedup_and_new_event(self):
        batch = [{'provider':'licensed','match_id':'42','innings':1,'over':1,'ball':1,'runs_bat':4}]
        sent = []
        b = LiveBridge(lambda:batch,lambda k,e:sent.append((k,e)))
        self.assertEqual(b.poll_once(),1)
        self.assertEqual(b.poll_once(),0)
        batch.append({'provider':'licensed','match_id':'42','innings':1,'over':1,'ball':2,'runs_bat':0})
        self.assertEqual(b.poll_once(),1)
        self.assertEqual(len(sent),2)
    def test_retry_after_persist_failure(self):
        event={'match_id':'1','event_id':'abc'}
        sent=[]
        def publish(k,e):
            if not sent:
                sent.append('failed')
                raise RuntimeError('database unavailable')
            sent.append(k)
        b=LiveBridge(lambda:[event],publish)
        with self.assertRaises(RuntimeError):b.poll_once()
        self.assertEqual(b.poll_once(),1)
    def test_reject_missing_identity(self):
        with self.assertRaises(ValueError):event_key({'match_id':'2'})
    def test_stop(self):
        b=LiveBridge(lambda:[],lambda k,e:None)
        b.stop()
        b.run()

if __name__=='__main__':unittest.main()
