/* Demo experience only. This never issues an authentication credential. */
(function(root){
'use strict';
let challenge=null;
root.SHDemoLogin={
 generate(code,number){
  if(!/^\+[1-9][0-9]{0,2}$/.test(code)||!/^\d{6,14}$/.test(number)||code.length-1+number.length>15)throw Error('Select country and enter a valid mobile number');
  const random=new Uint32Array(1);root.crypto.getRandomValues(random);
  challenge={otp:String(random[0]%1000000).padStart(6,'0'),expires:Date.now()+300000,tries:0};
  return challenge.otp;
 },
 verify(value){
  if(!challenge||Date.now()>=challenge.expires||challenge.tries>=5){challenge=null;return false}
  challenge.tries++;
  if(String(value)!==challenge.otp)return false;
  challenge=null;
  root.localStorage.setItem('shp_demo','0');
  root.localStorage.setItem('shp_demo_visit','1');
  root.location.hash='#/matches';return true;
 }
};
})(window);
