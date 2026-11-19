"""Viewer UI strings. English is the source. A language is reported as complete only when every key
is translated (coverage() below); otherwise the app says that some text falls back to English.
Proper names (teams, players, venues), numbers and official cricket terms (LBW, DLS, Super Over) are not translated.
The admin panel is English-only by design."""
KEYS = """nav.home nav.matches nav.experts nav.ai nav.assistant nav.accuracy nav.settings
state.loading state.empty state.error state.offline action.retry
label.competition label.all label.language label.theme theme.dark theme.light label.demo label.verified label.demo_toggle
acc.total acc.correct acc.incorrect acc.pending acc.void acc.overall acc.formula acc.by_league acc.by_expert acc.by_team
an.toss an.batfirst an.homeaway an.day an.venue
exp.verified exp.follow exp.following exp.history
ai.factors ai.toss_note ai.confidence ai.favours
home.live home.upcoming home.completed home.search
settings.saved settings.login settings.phone settings.get_code settings.verify settings.logout
mc.info mc.weather mc.toss mc.pitch mc.h2h mc.prediction mc.xi mc.fantasy mc.live mc.scorecard mc.commentary mc.partnerships mc.fow mc.graphs mc.result
mc.not_reported mc.no_pred mc.form mc.venue mc.status col.toss col.winner
fan.captain fan.vice fan.risk fan.free as.placeholder as.ask as.sources""".split()

def _mk(values):
    v = [x.strip() for x in values.strip().split("\n")]
    assert len(v) == len(KEYS), (len(v), len(KEYS))
    return dict(zip(KEYS, v))

EN = _mk("""
Home
Matches
Expert Tips
AI Prediction
Assistant
Accuracy
Settings
Loading…
No verified records yet
Could not load data
You are offline. Showing the last loaded data.
Retry
Competition
All
Language
Theme
Dark
Light
DEMO DATA
Verified
Show the demo dataset instead of real matches
Total predictions
Correct
Incorrect
Pending
Void
Overall accuracy
Accuracy = Correct / (Correct + Incorrect) × 100
League-wise
Expert-wise
Team-wise
Toss winner vs match winner
Batting first vs chasing
Home vs away
Day of week (UTC)
Venue
Verified expert
Follow
Following
Tip history
Why this prediction
The toss is a fair coin: 50% each.
Confidence
favours
Live
Upcoming
Completed
Search team or competition
Saved
Log in to keep your settings on all your devices
Mobile number
Get code
Log in
Log out
Info
Weather
Toss
Pitch
Head-to-head
Prediction
Playing XI
Fantasy XI
Live
Scorecard
Commentary
Partnerships
Fall of wickets
Graphs
Result
Not reported yet
No published prediction for this match yet
Form (last 5)
Venue
Status
Toss
Winner
Captain
Vice-captain
Risk
Free to play. No money involved.
Ask about a match, team, venue or a cricket Law
Ask
Sources
""")

HI = _mk("""
होम
मैच
विशेषज्ञ टिप्स
AI भविष्यवाणी
सहायक
सटीकता
सेटिंग्स
लोड हो रहा है…
अभी कोई सत्यापित रिकॉर्ड नहीं
डेटा लोड नहीं हो सका
आप ऑफ़लाइन हैं। अंतिम लोड किया गया डेटा दिख रहा है।
फिर से कोशिश करें
प्रतियोगिता
सभी
भाषा
थीम
डार्क
लाइट
डेमो डेटा
सत्यापित
असली मैचों की जगह डेमो डेटा दिखाएँ
कुल भविष्यवाणियाँ
सही
गलत
लंबित
रद्द
कुल सटीकता
सटीकता = सही / (सही + गलत) × 100
लीग अनुसार
विशेषज्ञ अनुसार
टीम अनुसार
टॉस विजेता बनाम मैच विजेता
पहले बल्लेबाज़ी बनाम चेज़
होम बनाम अवे
सप्ताह का दिन (UTC)
मैदान
सत्यापित विशेषज्ञ
फ़ॉलो करें
फ़ॉलो कर रहे हैं
टिप इतिहास
यह भविष्यवाणी क्यों
टॉस निष्पक्ष सिक्का है: दोनों के लिए 50%।
विश्वास
के पक्ष में
लाइव
आगामी
समाप्त
टीम या प्रतियोगिता खोजें
सहेजा गया
सभी डिवाइस पर सेटिंग्स रखने के लिए लॉग इन करें
मोबाइल नंबर
कोड पाएँ
लॉग इन
लॉग आउट
जानकारी
मौसम
टॉस
पिच
आमने-सामने
भविष्यवाणी
प्लेइंग XI
फ़ैंटेसी XI
लाइव
स्कोरकार्ड
कमेंट्री
साझेदारियाँ
विकेट पतन
ग्राफ़
परिणाम
अभी रिपोर्ट नहीं
इस मैच के लिए अभी कोई प्रकाशित भविष्यवाणी नहीं
फ़ॉर्म (पिछले 5)
मैदान
स्थिति
टॉस
विजेता
कप्तान
उप-कप्तान
जोखिम
मुफ़्त खेल। कोई पैसा नहीं।
किसी मैच, टीम, मैदान या क्रिकेट नियम के बारे में पूछें
पूछें
स्रोत
""")

TE = _mk("""
హోమ్
మ్యాచ్‌లు
నిపుణుల సూచనలు
AI అంచనా
సహాయకుడు
ఖచ్చితత్వం
సెట్టింగ్‌లు
లోడ్ అవుతోంది…
ఇంకా ధృవీకరించిన రికార్డులు లేవు
డేటా లోడ్ కాలేదు
మీరు ఆఫ్‌లైన్‌లో ఉన్నారు. చివరిగా లోడ్ అయిన డేటా చూపిస్తున్నాం.
మళ్ళీ ప్రయత్నించండి
పోటీ
అన్నీ
భాష
థీమ్
డార్క్
లైట్
డెమో డేటా
ధృవీకరించబడింది
నిజమైన మ్యాచ్‌లకు బదులు డెమో డేటా చూపించు
మొత్తం అంచనాలు
సరైనవి
తప్పు
పెండింగ్
రద్దు
మొత్తం ఖచ్చితత్వం
ఖచ్చితత్వం = సరైనవి / (సరైనవి + తప్పు) × 100
లీగ్ వారీగా
నిపుణుల వారీగా
జట్టు వారీగా
టాస్ విజేత vs మ్యాచ్ విజేత
ముందు బ్యాటింగ్ vs ఛేజింగ్
హోమ్ vs అవే
వారం రోజు (UTC)
మైదానం
ధృవీకరించిన నిపుణుడు
ఫాలో
ఫాలో అవుతున్నారు
సూచనల చరిత్ర
ఈ అంచనా ఎందుకు
టాస్ న్యాయమైన నాణెం: ఇరువురికీ 50%.
నమ్మకం
అనుకూలం
లైవ్
రాబోయేవి
పూర్తయినవి
జట్టు లేదా పోటీ వెతకండి
సేవ్ అయింది
అన్ని పరికరాల్లో సెట్టింగ్‌లు ఉండాలంటే లాగిన్ అవ్వండి
మొబైల్ నంబర్
కోడ్ పొందండి
లాగిన్
లాగౌట్
సమాచారం
వాతావరణం
టాస్
పిచ్
ముఖాముఖి
అంచనా
ప్లేయింగ్ XI
ఫాంటసీ XI
లైవ్
స్కోర్‌కార్డ్
వ్యాఖ్యానం
భాగస్వామ్యాలు
వికెట్ల పతనం
గ్రాఫ్‌లు
ఫలితం
ఇంకా నివేదించలేదు
ఈ మ్యాచ్‌కు ఇంకా ప్రచురించిన అంచనా లేదు
ఫామ్ (చివరి 5)
మైదానం
స్థితి
టాస్
విజేత
కెప్టెన్
వైస్-కెప్టెన్
రిస్క్
ఉచితంగా ఆడండి. డబ్బు ప్రమేయం లేదు.
మ్యాచ్, జట్టు, మైదానం లేదా క్రికెట్ నియమం గురించి అడగండి
అడగండి
మూలాలు
""")

TA = _mk("""
முகப்பு
போட்டிகள்
நிபுணர் குறிப்புகள்
AI கணிப்பு
உதவியாளர்
துல்லியம்
அமைப்புகள்
ஏற்றுகிறது…
இன்னும் சரிபார்க்கப்பட்ட பதிவுகள் இல்லை
தரவை ஏற்ற முடியவில்லை
நீங்கள் ஆஃப்லைனில் உள்ளீர்கள். கடைசியாக ஏற்றிய தரவு காட்டப்படுகிறது.
மீண்டும் முயற்சி
போட்டித் தொடர்
அனைத்தும்
மொழி
தீம்
இருண்ட
ஒளி
டெமோ தரவு
சரிபார்க்கப்பட்டது
உண்மையான போட்டிகளுக்குப் பதிலாக டெமோ தரவைக் காட்டு
மொத்த கணிப்புகள்
சரி
தவறு
நிலுவையில்
ரத்து
மொத்த துல்லியம்
துல்லியம் = சரி / (சரி + தவறு) × 100
லீக் வாரியாக
நிபுணர் வாரியாக
அணி வாரியாக
டாஸ் வென்றவர் vs போட்டி வென்றவர்
முதலில் பேட்டிங் vs துரத்தல்
சொந்த மைதானம் vs வெளி
வார நாள் (UTC)
மைதானம்
சரிபார்க்கப்பட்ட நிபுணர்
பின்தொடர்
பின்தொடர்கிறீர்கள்
குறிப்பு வரலாறு
இந்தக் கணிப்பு ஏன்
டாஸ் ஒரு நியாயமான நாணயம்: இருவருக்கும் 50%.
நம்பிக்கை
சாதகம்
நேரலை
வரவிருப்பவை
முடிந்தவை
அணி அல்லது தொடரைத் தேடுங்கள்
சேமிக்கப்பட்டது
எல்லா சாதனங்களிலும் அமைப்புகளை வைத்திருக்க உள்நுழையுங்கள்
மொபைல் எண்
குறியீடு பெறு
உள்நுழை
வெளியேறு
தகவல்
வானிலை
டாஸ்
ஆடுகளம்
நேருக்கு நேர்
கணிப்பு
விளையாடும் XI
ஃபேண்டஸி XI
நேரலை
ஸ்கோர்கார்டு
வர்ணனை
கூட்டணிகள்
விக்கெட் வீழ்ச்சி
வரைபடங்கள்
முடிவு
இன்னும் தெரிவிக்கப்படவில்லை
இந்தப் போட்டிக்கு இன்னும் வெளியிடப்பட்ட கணிப்பு இல்லை
ஃபார்ம் (கடைசி 5)
மைதானம்
நிலை
டாஸ்
வெற்றியாளர்
கேப்டன்
துணைக் கேப்டன்
அபாயம்
இலவசமாக விளையாடுங்கள். பணம் இல்லை.
போட்டி, அணி, மைதானம் அல்லது கிரிக்கெட் விதி பற்றிக் கேளுங்கள்
கேள்
ஆதாரங்கள்
""")

KN = _mk("""
ಮುಖಪುಟ
ಪಂದ್ಯಗಳು
ತಜ್ಞರ ಸಲಹೆಗಳು
AI ಮುನ್ಸೂಚನೆ
ಸಹಾಯಕ
ನಿಖರತೆ
ಸೆಟ್ಟಿಂಗ್‌ಗಳು
ಲೋಡ್ ಆಗುತ್ತಿದೆ…
ಇನ್ನೂ ಪರಿಶೀಲಿತ ದಾಖಲೆಗಳಿಲ್ಲ
ಡೇಟಾ ಲೋಡ್ ಆಗಲಿಲ್ಲ
ನೀವು ಆಫ್‌ಲೈನ್‌ನಲ್ಲಿದ್ದೀರಿ. ಕೊನೆಯದಾಗಿ ಲೋಡ್ ಆದ ಡೇಟಾ ತೋರಿಸಲಾಗುತ್ತಿದೆ.
ಮತ್ತೆ ಪ್ರಯತ್ನಿಸಿ
ಸ್ಪರ್ಧೆ
ಎಲ್ಲಾ
ಭಾಷೆ
ಥೀಮ್
ಡಾರ್ಕ್
ಲೈಟ್
ಡೆಮೊ ಡೇಟಾ
ಪರಿಶೀಲಿತ
ನಿಜವಾದ ಪಂದ್ಯಗಳ ಬದಲು ಡೆಮೊ ಡೇಟಾ ತೋರಿಸಿ
ಒಟ್ಟು ಮುನ್ಸೂಚನೆಗಳು
ಸರಿ
ತಪ್ಪು
ಬಾಕಿ
ರದ್ದು
ಒಟ್ಟು ನಿಖರತೆ
ನಿಖರತೆ = ಸರಿ / (ಸರಿ + ತಪ್ಪು) × 100
ಲೀಗ್ ಪ್ರಕಾರ
ತಜ್ಞರ ಪ್ರಕಾರ
ತಂಡದ ಪ್ರಕಾರ
ಟಾಸ್ ವಿಜೇತ vs ಪಂದ್ಯ ವಿಜೇತ
ಮೊದಲು ಬ್ಯಾಟಿಂಗ್ vs ಚೇಸಿಂಗ್
ತವರು vs ಹೊರಗಿನ
ವಾರದ ದಿನ (UTC)
ಮೈದಾನ
ಪರಿಶೀಲಿತ ತಜ್ಞ
ಅನುಸರಿಸಿ
ಅನುಸರಿಸುತ್ತಿದ್ದೀರಿ
ಸಲಹೆ ಇತಿಹಾಸ
ಈ ಮುನ್ಸೂಚನೆ ಏಕೆ
ಟಾಸ್ ನ್ಯಾಯಯುತ ನಾಣ್ಯ: ಇಬ್ಬರಿಗೂ 50%.
ವಿಶ್ವಾಸ
ಪರವಾಗಿ
ಲೈವ್
ಮುಂಬರುವ
ಮುಗಿದ
ತಂಡ ಅಥವಾ ಸ್ಪರ್ಧೆ ಹುಡುಕಿ
ಉಳಿಸಲಾಗಿದೆ
ಎಲ್ಲಾ ಸಾಧನಗಳಲ್ಲಿ ಸೆಟ್ಟಿಂಗ್‌ಗಳನ್ನು ಉಳಿಸಲು ಲಾಗಿನ್ ಮಾಡಿ
ಮೊಬೈಲ್ ಸಂಖ್ಯೆ
ಕೋಡ್ ಪಡೆಯಿರಿ
ಲಾಗಿನ್
ಲಾಗೌಟ್
ಮಾಹಿತಿ
ಹವಾಮಾನ
ಟಾಸ್
ಪಿಚ್
ಮುಖಾಮುಖಿ
ಮುನ್ಸೂಚನೆ
ಆಡುವ XI
ಫ್ಯಾಂಟಸಿ XI
ಲೈವ್
ಸ್ಕೋರ್‌ಕಾರ್ಡ್
ವೀಕ್ಷಕ ವಿವರಣೆ
ಜೊತೆಯಾಟಗಳು
ವಿಕೆಟ್ ಪತನ
ಗ್ರಾಫ್‌ಗಳು
ಫಲಿತಾಂಶ
ಇನ್ನೂ ವರದಿಯಾಗಿಲ್ಲ
ಈ ಪಂದ್ಯಕ್ಕೆ ಇನ್ನೂ ಪ್ರಕಟಿತ ಮುನ್ಸೂಚನೆ ಇಲ್ಲ
ಫಾರ್ಮ್ (ಕೊನೆಯ 5)
ಮೈದಾನ
ಸ್ಥಿತಿ
ಟಾಸ್
ವಿಜೇತ
ನಾಯಕ
ಉಪನಾಯಕ
ಅಪಾಯ
ಉಚಿತವಾಗಿ ಆಡಿ. ಹಣದ ವ್ಯವಹಾರವಿಲ್ಲ.
ಪಂದ್ಯ, ತಂಡ, ಮೈದಾನ ಅಥವಾ ಕ್ರಿಕೆಟ್ ನಿಯಮದ ಬಗ್ಗೆ ಕೇಳಿ
ಕೇಳಿ
ಮೂಲಗಳು
""")

BN = _mk("""
হোম
ম্যাচ
বিশেষজ্ঞ টিপস
AI পূর্বাভাস
সহকারী
নির্ভুলতা
সেটিংস
লোড হচ্ছে…
এখনও কোনো যাচাইকৃত রেকর্ড নেই
ডেটা লোড করা যায়নি
আপনি অফলাইনে আছেন। শেষবার লোড করা ডেটা দেখানো হচ্ছে।
আবার চেষ্টা করুন
প্রতিযোগিতা
সব
ভাষা
থিম
ডার্ক
লাইট
ডেমো ডেটা
যাচাইকৃত
আসল ম্যাচের বদলে ডেমো ডেটা দেখান
মোট পূর্বাভাস
সঠিক
ভুল
অপেক্ষমাণ
বাতিল
সামগ্রিক নির্ভুলতা
নির্ভুলতা = সঠিক / (সঠিক + ভুল) × 100
লিগ অনুযায়ী
বিশেষজ্ঞ অনুযায়ী
দল অনুযায়ী
টস জয়ী বনাম ম্যাচ জয়ী
আগে ব্যাটিং বনাম রান তাড়া
হোম বনাম অ্যাওয়ে
সপ্তাহের দিন (UTC)
মাঠ
যাচাইকৃত বিশেষজ্ঞ
অনুসরণ করুন
অনুসরণ করছেন
টিপসের ইতিহাস
এই পূর্বাভাস কেন
টস একটি ন্যায্য মুদ্রা: দুই দলের জন্য 50%।
আস্থা
পক্ষে
লাইভ
আসন্ন
সমাপ্ত
দল বা প্রতিযোগিতা খুঁজুন
সংরক্ষিত
সব ডিভাইসে সেটিংস রাখতে লগ ইন করুন
মোবাইল নম্বর
কোড নিন
লগ ইন
লগ আউট
তথ্য
আবহাওয়া
টস
পিচ
মুখোমুখি
পূর্বাভাস
প্লেয়িং XI
ফ্যান্টাসি XI
লাইভ
স্কোরকার্ড
ধারাভাষ্য
জুটি
উইকেট পতন
গ্রাফ
ফলাফল
এখনও জানানো হয়নি
এই ম্যাচের জন্য এখনও প্রকাশিত পূর্বাভাস নেই
ফর্ম (শেষ 5)
মাঠ
অবস্থা
টস
বিজয়ী
অধিনায়ক
সহ-অধিনায়ক
ঝুঁকি
বিনামূল্যে খেলুন। কোনো টাকা নেই।
ম্যাচ, দল, মাঠ বা ক্রিকেটের আইন নিয়ে প্রশ্ন করুন
জিজ্ঞাসা
সূত্র
""")

MR = _mk("""
मुख्यपृष्ठ
सामने
तज्ज्ञांच्या टिप्स
AI अंदाज
सहाय्यक
अचूकता
सेटिंग्ज
लोड होत आहे…
अद्याप सत्यापित नोंदी नाहीत
डेटा लोड करता आला नाही
तुम्ही ऑफलाइन आहात. शेवटचा लोड केलेला डेटा दाखवत आहोत.
पुन्हा प्रयत्न करा
स्पर्धा
सर्व
भाषा
थीम
डार्क
लाइट
डेमो डेटा
सत्यापित
खऱ्या सामन्यांऐवजी डेमो डेटा दाखवा
एकूण अंदाज
बरोबर
चूक
प्रलंबित
रद्द
एकूण अचूकता
अचूकता = बरोबर / (बरोबर + चूक) × 100
लीगनुसार
तज्ज्ञांनुसार
संघानुसार
टॉस विजेता विरुद्ध सामना विजेता
आधी फलंदाजी विरुद्ध पाठलाग
घरचे विरुद्ध बाहेरचे
आठवड्याचा दिवस (UTC)
मैदान
सत्यापित तज्ज्ञ
फॉलो करा
फॉलो करत आहात
टिप्सचा इतिहास
हा अंदाज का
टॉस हे निष्पक्ष नाणे आहे: दोघांना 50%.
विश्वास
च्या बाजूने
लाइव्ह
आगामी
पूर्ण
संघ किंवा स्पर्धा शोधा
जतन केले
सर्व उपकरणांवर सेटिंग्ज ठेवण्यासाठी लॉग इन करा
मोबाइल क्रमांक
कोड मिळवा
लॉग इन
लॉग आउट
माहिती
हवामान
टॉस
खेळपट्टी
आमनेसामने
अंदाज
प्लेइंग XI
फँटसी XI
लाइव्ह
स्कोअरकार्ड
समालोचन
भागीदाऱ्या
विकेट पतन
आलेख
निकाल
अद्याप कळवलेले नाही
या सामन्यासाठी अद्याप प्रकाशित अंदाज नाही
फॉर्म (शेवटचे 5)
मैदान
स्थिती
टॉस
विजेता
कर्णधार
उपकर्णधार
जोखीम
मोफत खेळा. पैशाचा व्यवहार नाही.
सामना, संघ, मैदान किंवा क्रिकेट नियमाबद्दल विचारा
विचारा
स्रोत
""")

UR = _mk("""
ہوم
میچز
ماہرین کی ٹپس
AI پیش گوئی
معاون
درستی
ترتیبات
لوڈ ہو رہا ہے…
ابھی کوئی تصدیق شدہ ریکارڈ نہیں
ڈیٹا لوڈ نہیں ہو سکا
آپ آف لائن ہیں۔ آخری لوڈ شدہ ڈیٹا دکھایا جا رہا ہے۔
دوبارہ کوشش کریں
مقابلہ
سب
زبان
تھیم
ڈارک
لائٹ
ڈیمو ڈیٹا
تصدیق شدہ
اصل میچوں کی جگہ ڈیمو ڈیٹا دکھائیں
کل پیش گوئیاں
درست
غلط
زیر التوا
منسوخ
مجموعی درستی
درستی = درست / (درست + غلط) × 100
لیگ کے لحاظ سے
ماہر کے لحاظ سے
ٹیم کے لحاظ سے
ٹاس جیتنے والا بمقابلہ میچ جیتنے والا
پہلے بیٹنگ بمقابلہ ہدف کا تعاقب
ہوم بمقابلہ اوے
ہفتے کا دن (UTC)
میدان
تصدیق شدہ ماہر
فالو کریں
فالو کر رہے ہیں
ٹپس کی تاریخ
یہ پیش گوئی کیوں
ٹاس ایک منصفانہ سکہ ہے: دونوں کے لیے 50%۔
اعتماد
کے حق میں
لائیو
آنے والے
مکمل
ٹیم یا مقابلہ تلاش کریں
محفوظ ہو گیا
تمام آلات پر ترتیبات رکھنے کے لیے لاگ ان کریں
موبائل نمبر
کوڈ حاصل کریں
لاگ ان
لاگ آؤٹ
معلومات
موسم
ٹاس
پچ
آمنے سامنے
پیش گوئی
پلیئنگ XI
فینٹسی XI
لائیو
اسکور کارڈ
کمنٹری
شراکتیں
وکٹوں کا گرنا
گراف
نتیجہ
ابھی رپورٹ نہیں ہوا
اس میچ کے لیے ابھی کوئی شائع شدہ پیش گوئی نہیں
فارم (آخری 5)
میدان
حالت
ٹاس
فاتح
کپتان
نائب کپتان
خطرہ
مفت کھیلیں۔ کوئی پیسہ شامل نہیں۔
کسی میچ، ٹیم، میدان یا کرکٹ قانون کے بارے میں پوچھیں
پوچھیں
ذرائع
""")

ES = _mk("""
Inicio
Partidos
Consejos de expertos
Predicción IA
Asistente
Precisión
Ajustes
Cargando…
Aún no hay registros verificados
No se pudieron cargar los datos
Estás sin conexión. Se muestran los últimos datos cargados.
Reintentar
Competición
Todas
Idioma
Tema
Oscuro
Claro
DATOS DEMO
Verificado
Mostrar datos demo en lugar de partidos reales
Predicciones totales
Correctas
Incorrectas
Pendientes
Anuladas
Precisión global
Precisión = Correctas / (Correctas + Incorrectas) × 100
Por liga
Por experto
Por equipo
Ganador del sorteo vs ganador del partido
Batear primero vs perseguir
Local vs visitante
Día de la semana (UTC)
Estadio
Experto verificado
Seguir
Siguiendo
Historial de consejos
Por qué esta predicción
El sorteo es una moneda justa: 50% para cada uno.
Confianza
a favor de
En vivo
Próximos
Finalizados
Buscar equipo o competición
Guardado
Inicia sesión para conservar tus ajustes en todos tus dispositivos
Número de móvil
Obtener código
Iniciar sesión
Cerrar sesión
Información
Clima
Sorteo
Pitch
Cara a cara
Predicción
Playing XI
Fantasy XI
En vivo
Marcador
Comentarios
Asociaciones
Caída de wickets
Gráficos
Resultado
Aún no informado
Aún no hay predicción publicada para este partido
Forma (últimos 5)
Estadio
Estado
Sorteo
Ganador
Capitán
Vicecapitán
Riesgo
Juego gratuito. Sin dinero.
Pregunta por un partido, equipo, estadio o una Ley del cricket
Preguntar
Fuentes
""")

STRINGS = {"en": EN, "hi": HI, "te": TE, "ta": TA, "kn": KN, "bn": BN, "mr": MR, "ur": UR, "es": ES}

def bundle(code):
    out = dict(EN)
    out.update(STRINGS.get(code, {}))
    return out

def coverage(code):
    """Share of English UI keys that have a real translation (English itself is 100)."""
    if code == "en":
        return 100
    have = STRINGS.get(code, {})
    return int(100 * sum(1 for k in EN if k in have) / len(EN))
