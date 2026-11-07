"""Native-language book furniture; never a fallback translation of reader quotations."""
BOOK_IDS=['bukhari','muslim','ahmad','abudawud','tirmidhi','nasai','ibnmajah','ibnhibban','malik']
# name, surah label, ayah label, credits title, model-translation notice, source book names
COPY={
'en':['English','Surah','Ayah','Translation and edition credits','AI translated — needs verification. Model-assisted checks are not a substitute for review by a qualified human reader.',['Sahih al-Bukhari','Sahih Muslim','Musnad Ahmad','Sunan Abi Dawud','Jami al-Tirmidhi','Sunan al-Nasai','Sunan Ibn Majah','Sahih Ibn Hibban','Al-Muwatta of Malik']],
'ar':['العربية','سورة','آية','مصادر الترجمة والنقول','',['صحيح البخاري','صحيح مسلم','مسند أحمد','سنن أبي داود','جامع الترمذي','سنن النسائي','سنن ابن ماجه','صحيح ابن حبان','موطأ مالك']],
'ur':['اردو','سورۃ','آیت','تراجم اور اقتباسات کے مصادر','مصنوعی ذہانت کی مدد سے ترجمہ کیا گیا ہے؛ تصدیق درکار ہے۔ ماڈل کی مدد سے کی گئی جانچ کسی اہل قاری کے جائزے کا متبادل نہیں ہے۔',['صحیح بخاری','صحیح مسلم','مسند احمد','سنن ابی داود','جامع ترمذی','سنن نسائی','سنن ابن ماجہ','صحیح ابن حبان','موطأ امام مالک']],
'id':['Bahasa Indonesia','Surah','Ayat','Kredit terjemahan dan edisi','Diterjemahkan dengan bantuan kecerdasan buatan dan perlu diverifikasi. Pemeriksaan berbantuan model tidak menggantikan peninjauan oleh pembaca yang berkompeten.',['Sahih al-Bukhari','Sahih Muslim','Musnad Ahmad','Sunan Abu Dawud','Jami al-Tirmidzi','Sunan al-Nasai','Sunan Ibnu Majah','Sahih Ibnu Hibban','Al-Muwatta Imam Malik']],
'ms':['Bahasa Melayu','Surah','Ayat','Sumber terjemahan dan edisi','Terjemahan dengan bantuan kecerdasan buatan — perlu disahkan. Semakan berbantukan model bukan pengganti semakan oleh pembaca yang berkelayakan.',['Sahih al-Bukhari','Sahih Muslim','Musnad Ahmad','Sunan Abu Dawud','Jami al-Tirmizi','Sunan al-Nasai','Sunan Ibn Majah','Sahih Ibn Hibban','Al-Muwatta Imam Malik']],
'bn':['বাংলা','সূরা','আয়াত','অনুবাদ ও উদ্ধৃতির উৎস','কৃত্রিম বুদ্ধিমত্তার সহায়তায় অনূদিত — যাচাই প্রয়োজন। মডেলের সাহায্যে করা পরীক্ষা কোনো যোগ্য পাঠকের পর্যালোচনার বিকল্প নয়।',['সহিহ বুখারি','সহিহ মুসলিম','মুসনাদ আহমাদ','সুনান আবু দাউদ','জামি তিরমিজি','সুনান নাসাঈ','সুনান ইবনে মাজাহ','সহিহ ইবনে হিব্বান','মুয়াত্তা ইমাম মালিক']],
'tr':['Türkçe','Sure','Ayet','Çeviri ve baskı kaynakları','Yapay zekâ yardımıyla çevrilmiştir; doğrulanması gerekir. Model destekli kontroller, yetkin bir okuyucunun incelemesinin yerini tutmaz.',['Sahih-i Buhârî','Sahih-i Müslim','Ahmed b. Hanbel’in Müsned’i','Sünen-i Ebû Dâvûd','Tirmizî’nin Câmi‘i','Sünen-i Nesâî','Sünen-i İbn Mâce','Sahih-i İbn Hibbân','İmam Mâlik’in Muvatta’ı']],
'fr':['Français','Sourate','verset','Sources des traductions et des éditions','Traduction réalisée avec l’aide de l’intelligence artificielle — à vérifier. Les contrôles assistés par un modèle ne remplacent pas la révision d’un lecteur qualifié.',['Sahîh d’al-Boukhârî','Sahîh de Mouslim','Mousnad d’Ahmad','Sounan d’Abou Dâwoud','Jâmi‘ d’at-Tirmidhî','Sounan d’an-Nasâ’î','Sounan d’Ibn Mâjah','Sahîh d’Ibn Hibbân','Mouwatta de Mâlik']],
'pt-BR':['Português','Surata','versículo','Créditos das traduções e edições','Tradução com auxílio de inteligência artificial — requer verificação. As verificações assistidas por modelos não substituem a revisão por um leitor qualificado.',['Sahih de al-Bukhari','Sahih de Muslim','Musnad de Ahmad','Sunan de Abu Dawud','Jami de al-Tirmidhi','Sunan de al-Nasai','Sunan de Ibn Majah','Sahih de Ibn Hibban','Al-Muwatta de Malik']],
'hi':['हिन्दी','सूरा','आयत','अनुवाद और उद्धरणों के स्रोत','कृत्रिम बुद्धिमत्ता की सहायता से अनूदित — सत्यापन आवश्यक है। मॉडल की सहायता से की गई जाँच किसी योग्य पाठक की समीक्षा का विकल्प नहीं है।',['सहीह बुख़ारी','सहीह मुस्लिम','मुस्नद अहमद','सुनन अबू दाऊद','जामि तिर्मिज़ी','सुनन नसाई','सुनन इब्ने माजा','सहीह इब्ने हिब्बान','मुवत्ता इमाम मालिक']],
'ru':['Русский','Сура','аят','Источники переводов и изданий','Переведено с помощью искусственного интеллекта — требуется проверка. Проверки с помощью модели не заменяют рецензию компетентного читателя.',['Сахих аль-Бухари','Сахих Муслима','Муснад Ахмада','Сунан Абу Дауда','Джами ат-Тирмизи','Сунан ан-Насаи','Сунан Ибн Маджи','Сахих Ибн Хиббана','Аль-Муватта имама Малика']],
'es':['Español','Sura','aleya','Fuentes de las traducciones y ediciones','Traducido con ayuda de inteligencia artificial; requiere verificación. Las comprobaciones asistidas por modelos no sustituyen la revisión de un lector cualificado.',['Sahih de Al-Bujari','Sahih de Muslim','Musnad de Ahmad','Sunan de Abu Daud','Yami de At-Tirmidhi','Sunan de An-Nasai','Sunan de Ibn Mayah','Sahih de Ibn Hibban','Al-Muwatta de Malik']],
'fa':['فارسی','سوره','آیه','منابع ترجمه و نقل‌قول‌ها','این متن با کمک هوش مصنوعی ترجمه شده و نیازمند بررسی است. بررسی به کمک مدل جایگزین بازبینی فردی شایسته نیست.',['صحیح بخاری','صحیح مسلم','مسند احمد','سنن ابوداوود','جامع ترمذی','سنن نسائی','سنن ابن ماجه','صحیح ابن حبان','موطأ مالک']],
'de':['Deutsch','Sure','Vers','Quellen der Übersetzungen und Ausgaben','Mit künstlicher Intelligenz übersetzt — Überprüfung erforderlich. Modellgestützte Prüfungen ersetzen nicht die Prüfung durch einen fachkundigen Leser.',['Sahih al-Buchari','Sahih Muslim','Musnad Ahmad','Sunan Abu Dawud','Dschami at-Tirmidhi','Sunan an-Nasai','Sunan Ibn Madscha','Sahih Ibn Hibban','Al-Muwatta von Malik']],
'zh-CN':['简体中文','章','节','译文与版本来源','本资料由人工智能辅助翻译，仍需核实。模型辅助检查不能替代合格读者的审核。',['《布哈里圣训实录》','《穆斯林圣训实录》','《艾哈迈德圣训集》','《艾布·达伍德圣训集》','《提尔密济圣训集》','《奈萨仪圣训集》','《伊本·马哲圣训集》','《伊本·希班圣训实录》','《马立克穆宛塔圣训集》']],
'uz':['O‘zbekcha','Sura','oyat','Tarjima va nashr manbalari','Sun’iy intellekt yordamida tarjima qilingan, tekshirish talab etiladi. Model yordamidagi tekshiruvlar malakali o‘quvchi ko‘rigini almashtirmaydi.',['Sahih al-Buxoriy','Sahih Muslim','Musnad Ahmad','Sunan Abu Dovud','Jome at-Termiziy','Sunan an-Nasoiy','Sunan Ibn Moja','Sahih Ibn Hibbon','Imom Molikning Muvatto asari']],
'th':['ไทย','สูเราะฮ์','อายะฮ์','แหล่งที่มาของคำแปลและฉบับพิมพ์','แปลโดยใช้ปัญญาประดิษฐ์ช่วยและยังต้องตรวจสอบ การตรวจด้วยแบบจำลองไม่อาจทดแทนการทบทวนโดยผู้อ่านที่มีความรู้เหมาะสมได้',['เศาะฮีห์อัลบุคอรี','เศาะฮีห์มุสลิม','มุสนัดอะห์มัด','สุนันอบูดาวูด','ญามิอ์อัตติรมิซี','สุนันอันนะสาอี','สุนันอิบนุมาญะฮ์','เศาะฮีห์อิบนุหิบบาน','อัลมุวัฏเฏาะอ์ของอิมามมาลิก']],
'vi':['Tiếng Việt','Chương','câu','Nguồn bản dịch và ấn bản','Bản dịch có sự hỗ trợ của trí tuệ nhân tạo, cần được kiểm chứng. Việc kiểm tra bằng mô hình không thay thế cho sự rà soát của người đọc có đủ kiến thức.',['Bộ Sahih Al-Bukhari','Bộ Sahih Muslim','Bộ Musnad Ahmad','Bộ Sunan Abu Dawud','Bộ Jami At-Tirmidhi','Bộ Sunan An-Nasai','Bộ Sunan Ibn Majah','Bộ Sahih Ibn Hibban','Bộ Al-Muwatta của Malik']],
'ja':['日本語','章','節','翻訳と版の出典','人工知能の支援により翻訳された内容であり、確認が必要です。モデルによる点検は、適切な知識を持つ読者による確認に代わるものではありません。',['『サヒーフ・アル＝ブハーリー』','『サヒーフ・ムスリム』','『ムスナド・アフマド』','『スナン・アブー・ダーウード』','『ジャーミウ・アッ＝ティルミズィー』','『スナン・アン＝ナサーイー』','『スナン・イブン・マージャ』','『サヒーフ・イブン・ヒッバーン』','イマーム・マーリクの『ムワッタ』']],
# Filipino source convention: HadeethEnc tl/11256 uses Kabanatang Al-Ikhlās;
# QuranEnc's Tagalog Rowwad edition retains Al-Ikhlāṣ as the proper chapter name.
# Localize the label, preserving the approved Filipino source's title spelling.
'fil':['Filipino','Kabanata','talata','Mga pinagmulan ng salin at edisyon','Salin na ginawa sa tulong ng artipisyal na intelihensiya at nangangailangan ng pagsusuri. Hindi mapapalitan ng pagsusuri ng modelo ang pagsusuri ng isang kuwalipikadong mambabasa.',['Sahih ni al-Bukhari','Sahih ni Muslim','Musnad ni Ahmad','Sunan ni Abu Dawud','Jami ni al-Tirmidhi','Sunan ni al-Nasai','Sunan ni Ibn Majah','Sahih ni Ibn Hibban','Al-Muwatta ni Malik']]
}
NON_LATIN={'ar','ur','fa','bn','hi','ru','zh-CN','th','ja'}
NATIVE_DIGITS={'ar':'٠١٢٣٤٥٦٧٨٩','ur':'۰۱۲۳۴۵۶۷۸۹','fa':'۰۱۲۳۴۵۶۷۸۹','bn':'০১২৩৪৫৬৭৮৯','hi':'०१२३४५६७८९'}
SURAH_OVERRIDES={
'ur':{1:'الفاتحہ',18:'الکہف',35:'فاطر',112:'الاخلاص'},
'bn':{1:'আল-ফাতিহা',18:'আল-কাহফ',35:'ফাতির',112:'আল-ইখলাস'},
'hi':{1:'अल-फ़ातिहा',18:'अल-कह्फ़',35:'फ़ातिर',112:'अल-इख़लास'},
'th':{1:'อัลฟาติหะฮ์',18:'อัลกะฮ์ฟ์',35:'ฟาฏิร',112:'อัลอิคลาศ'}}

def locale(lang):
    name,surah,ayah,credits,notice,books=COPY[lang]
    return {'nativeName':name,'surahLabel':surah,'ayahLabel':ayah,'creditsTitle':credits,'notice':notice,'hadithBooks':dict(zip(BOOK_IDS,books))}
DOWNLOADS={
'en':('Download editable book','Download reading copy'),
'ar':('تنزيل الكتاب القابل للتحرير','تنزيل نسخة القراءة'),
'ur':('قابل تدوین کتاب ڈاؤن لوڈ کریں','مطالعے کی نقل ڈاؤن لوڈ کریں'),
'id':('Unduh buku yang dapat disunting','Unduh salinan bacaan'),
'ms':('Muat turun buku boleh sunting','Muat turun salinan bacaan'),
'bn':('সম্পাদনাযোগ্য বই ডাউনলোড করুন','পাঠের অনুলিপি ডাউনলোড করুন'),
'tr':('Düzenlenebilir kitabı indir','Okuma nüshasını indir'),
'fr':('Télécharger le livre modifiable','Télécharger la version de lecture'),
'pt-BR':('Baixar livro editável','Baixar versão de leitura'),
'hi':('संपादन योग्य पुस्तक डाउनलोड करें','पढ़ने की प्रति डाउनलोड करें'),
'ru':('Скачать редактируемую книгу','Скачать версию для чтения'),
'es':('Descargar libro editable','Descargar versión de lectura'),
'fa':('دریافت کتاب ویرایش‌پذیر','دریافت نسخهٔ مطالعه'),
'de':('Bearbeitbares Buch herunterladen','Leseausgabe herunterladen'),
'zh-CN':('下载可编辑书籍','下载阅读版'),
'uz':('Tahrirlanadigan kitobni yuklab olish','O‘qish nusxasini yuklab olish'),
'th':('ดาวน์โหลดหนังสือที่แก้ไขได้','ดาวน์โหลดฉบับอ่าน'),
'vi':('Tải sách có thể chỉnh sửa','Tải bản để đọc'),
'ja':('編集可能な書籍をダウンロード','閲覧用の書籍をダウンロード'),
'fil':('I-download ang nae-edit na aklat','I-download ang kopyang pambasa')}
