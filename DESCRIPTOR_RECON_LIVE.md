=== DESCRIPTOR CANDIDATE RECON (live DB) ===
Reference villages loaded: 3084
Corpus texts scanned: 102

WORD: حرش
  distinct prefixed phrases in corpus: 2
  villages whose ref_name STARTS with this word: 0
  token count inside any village name: 0
  strip risk: LOW
  example phrases:
    - حرش علي الطاهر
      remainder after strip: 'علي الطاهر' -> ['علي الطاهر']
    - حرش عيتا الجبل
      remainder after strip: 'عيتا الجبل' -> ['عيتا الجبل الزط']
  RECOMMENDATION: CONFIRMED STRIP CANDIDATE

WORD: وادي
  distinct prefixed phrases in corpus: 8
  villages whose ref_name STARTS with this word: 19
    examples: ['وادي الليمون', 'وادي الجاموس', 'وادي جزين']
  token count inside any village name: 22
  strip risk: HIGH
  example phrases:
    - وادي زبقين
      remainder after strip: 'زبقين' -> ['زبقين']
    - وادي زبقين وعلي الطاهر وتفجير
      remainder after strip: 'زبقين وعلي الطاهر وتفجير' -> ['علي الطاهر', 'زبقين']
    - وادي زبقين ومحيط تله علي
      remainder after strip: 'زبقين ومحيط تله علي' -> ['زبقين']
    - وادي السلوقي جنوب لبنان
      remainder after strip: 'السلوقي جنوب لبنان' -> ['سلوقي']
    - وادي السلوقي T
      remainder after strip: 'السلوقي T' -> ['سلوقي']
    - وادي السلوقي
      remainder after strip: 'السلوقي' -> ['سلوقي']
    - وادي زبقين T
      remainder after strip: 'زبقين T' -> ['زبقين']
    - وادي الحجير
      remainder after strip: 'الحجير' -> []
  RECOMMENDATION: DO NOT STRIP — registered village names start with this word

WORD: اطراف
  distinct prefixed phrases in corpus: 7
  villages whose ref_name STARTS with this word: 0
  token count inside any village name: 0
  strip risk: LOW
  example phrases:
    - اطراف بلده ميفدون
      remainder after strip: 'بلده ميفدون' -> ['ميفدون']
    - اطراف بلده زبقين جنوب لبنان
      remainder after strip: 'بلده زبقين جنوب لبنان' -> ['زبقين']
    - اطراف زبقين
      remainder after strip: 'زبقين' -> ['زبقين']
    - اطراف ياطر
      remainder after strip: 'ياطر' -> ['ياطر']
    - اطراف النبطيه، بعدما حوصر فيه
      remainder after strip: 'النبطيه، بعدما حوصر فيه' -> []
    - اطراف بلده ياطر
      remainder after strip: 'بلده ياطر' -> ['ياطر']
    - اطراف بلده كفرا في قضاء
      remainder after strip: 'بلده كفرا في قضاء' -> ['كفر']
  RECOMMENDATION: CONFIRMED STRIP CANDIDATE

WORD: محيط
  distinct prefixed phrases in corpus: 3
  villages whose ref_name STARTS with this word: 0
  token count inside any village name: 0
  strip risk: LOW
  example phrases:
    - محيط تله الدبشه لجهه النبطيه
      remainder after strip: 'تله الدبشه لجهه النبطيه' -> []
    - محيط علي الطاهر
      remainder after strip: 'علي الطاهر' -> ['علي الطاهر']
    - محيط تله علي الطاهر
      remainder after strip: 'تله علي الطاهر' -> ['علي الطاهر']
  RECOMMENDATION: CONFIRMED STRIP CANDIDATE

WORD: مشاع
  distinct prefixed phrases in corpus: 1
  villages whose ref_name STARTS with this word: 4
    examples: ['مشاع الجبه', 'مشاع فاريا', 'مشاع كفر ذبيان']
  token count inside any village name: 4
  strip risk: HIGH
  example phrases:
    - مشاع المنصوري
      remainder after strip: 'المنصوري' -> ['المنصوري', 'صور']
  RECOMMENDATION: DO NOT STRIP — registered village names start with this word

WORD: جنوب
  distinct prefixed phrases in corpus: 2
  villages whose ref_name STARTS with this word: 0
  token count inside any village name: 0
  strip risk: LOW
  example phrases:
    - جنوب لبنان
      remainder after strip: 'لبنان' -> []
    - جنوب لبنان T
      remainder after strip: 'لبنان T' -> []
  RECOMMENDATION: CONFIRMED STRIP CANDIDATE

WORD: جبل
  distinct prefixed phrases in corpus: 1
  villages whose ref_name STARTS with this word: 2
    examples: ['جبل طوره', 'جبل الشعيبه']
  token count inside any village name: 2
  strip risk: HIGH
  example phrases:
    - جبل مشغره
      remainder after strip: 'مشغره' -> ['مشغره']
  RECOMMENDATION: DO NOT STRIP — registered village names start with this word

WORD: حي
  distinct prefixed phrases in corpus: 2
  villages whose ref_name STARTS with this word: 0
  token count inside any village name: 1
  strip risk: LOW
  example phrases:
    - حي جبيل
      remainder after strip: 'جبيل' -> ['عيناتا بنت جبيل', 'كفرا بنت جبيل', 'مشمش جبيل']
    - حي جبيل T
      remainder after strip: 'جبيل T' -> ['جبيل']
  RECOMMENDATION: CONFIRMED STRIP CANDIDATE

=== PROPOSED STRIP-LIST (pending your confirmation) ===
حرش, اطراف, محيط, جنوب, حي

=== PRIOR OFFLINE PROPOSAL ===
strip: حرش, خراج, اطراف
exclude (village-name prefix): وادي, مشاع, ضهر, مزارع

=== DELTA VS PRIOR PROPOSAL ===
  strip-list additions: ['جنوب', 'حي', 'محيط']
  strip-list removals: ['خراج']
  prior exclude-list words that ARE registered village prefixes: ['ضهر', 'مزارع', 'مشاع', 'وادي']

=== KNOWN CASE: حرش عيتا الجبل ===
  ref_name match: عيتا الجبل الزط