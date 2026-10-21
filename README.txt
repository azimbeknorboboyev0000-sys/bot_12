KINO BOT — Python 3.10 yoki yangiroq. Qo‘shimcha paket kerak emas.

ISHLATISH
1. BotFather bergan tokenni .env faylidagi BOT_TOKEN qiymatiga kiriting.
2. python bot.py
3. Botga /id yuboring. Chiqqan raqamni .env ichidagi ADMIN_IDS ga kiriting.
   Bir nechta admin: ADMIN_IDS=123456789,987654321
4. Botni Ctrl+C bilan to‘xtatib, python bot.py orqali qayta ishga tushiring.
5. /admin tugmali boshqaruv panelini ochadi. Oddiy foydalanuvchi kino kodini yuboradi.

SOZLAMALAR
BOT_TOKEN — haqiqiy token faqat .env ichida saqlansin.
ADMIN_IDS — vergul bilan ajratilgan Telegram foydalanuvchi IDlari.
CHANNEL_ID — ixtiyoriy saqlash kanalining manfiy IDsi. Ishlatmasangiz bo‘sh qoldiring.
Saqlash kanalini majburiy obuna kanallari bilan adashtirmang; ular alohida sozlanadi.
.env.example faqat namunaviy qiymatlar saqlaydi. Haqiqiy tokenni unga yozmang.
Agar token ilgari oshkor bo‘lgan bo‘lsa, BotFather orqali yangisini oling.
.gitignore sirlar, bazalar va vaqtinchalik fayllarni yangi Git kuzatuvidan chiqaradi.
Oldin kuzatilgan .env bo‘lsa, git rm --cached .env bilan indeksdan chiqaring.

KINOLAR
Kino havolasi: https://t.me/BOT_USERNAME?start=8
Bot /start 8 olganda 8 kodini oddiy xabardagi kabi qidiradi va obunani tekshiradi.
Obuna yetishmasa kod saqlanadi; Obunani tekshirish bosilgach o‘sha kino yuboriladi.
Parametrsiz /start odatdagi boshlang‘ich xabarni ochadi.
Har bir yuborilgan kino tagida 📤 Ulashish tugmasi chiqadi.
Tugma Telegram ulashish oynasida kino nomi va botdagi havolasini tayyorlaydi; video ulashilmaydi.
Reklama tugmasi saqlanadi, ulashish tugmasi alohida qatorda joylashadi.
Kino qo‘shilgach bot getMe orqali o‘z username’ini aniqlab, tayyor havolani chiqaradi.
/admin → Kino qo‘shish → kod → nom → tavsif (- bo‘lsa tavsifsiz) → video.
Video fayl, yo‘naltirilgan video yoki kanal xabarining chat_id | message_id qiymatini yuboring.
Kanal xabari avval adminga yo‘naltirib tekshiriladi; matnli xabar kino sifatida saqlanmaydi.
Himoyalangan kanal kontenti bilan ishlash uchun kanal himoyasini o‘chirish zarur.
Tez qo‘shish ham saqlangan: video izohi 125 | Kino nomi | Ixtiyoriy tavsif.
CHANNEL_ID sozlangan bo‘lsa, shu kanaldagi video postlari ham katalogga qo‘shiladi.
Kanal video posti tahrirlansa, o‘sha manbaga tegishli katalog yozuvi yangilanadi.
001 va 1 — alohida kodlar. Takroriy kod mavjud kinoni almashtirmaydi.
Tahrirlash panelida nom, tavsif yoki videoni almashtirish mumkin.
O‘chirish faqat katalog yozuviga ta’sir qiladi. Asl kanal xabari o‘chirilmaydi.
/delete 125 tasdiqlash oynasini ochadi; /stats statistikani ko‘rsatadi.
Video serverga yuklanmaydi; bazada file_id yoki kanal xabari manzili saqlanadi.

MAJBURIY OBUNA
/admin → Majburiy kanallar → Kanal qo‘shish → nom → chat_id yoki @username → taklif havolasi.
Ochiq kanal: https://t.me/kanal. Yopiq kanal: https://t.me/+taklif.
Botni avval kanal administratori qiling. Bot kanal turi va admin maqomini tekshiradi.
Havolaning aynan shu kanalga tegishliligi va yopiq taklifning amal qilishini admin tekshiradi:
Telegram API ixtiyoriy taklif havolasini tekshirish imkonini bermaydi.
Paneldan har bir kanalni yoqish/o‘chirish yoki ro‘yxatdan olib tashlash mumkin.
Har bir kino berilishidan oldin barcha faol kanallar tekshiriladi.
Qo‘shilish so‘rovi yuborish yetmaydi; kanal uni tasdiqlashi kerak.
Obunani tekshirish tugmasi oldin so‘ralgan kinoni avtomatik yuboradi.
Telegram yoki ruxsat xatosida kino yuborilmaydi, foydalanuvchiga vaqtinchalik xato bildiriladi.
Tashxis loglari token yoki shaxsiy xabarlarni chiqarmaydi; kanal IDsi va xato kodi yoziladi.

REKLAMA
/admin → Reklama boshqaruvi → Kino reklamasini sozlash.
Matn va ixtiyoriy tugma kiriting: Batafsil | https://example.com
Tugmasiz saqlash uchun - yuboring. Reklamani paneldan yoqish/o‘chirish mumkin.
Reklama kino izohiga qo‘shiladi; 1024 belgilik chegaradan oshsa alohida xabar yuboriladi.
Kino nomi va tavsifi bazada reklamasiz saqlanadi.
Foydalanuvchilarga tarqatish → matn/rasm/video → ixtiyoriy URL tugmasi.
Admin reklama ko‘rinishi va bazadagi qabul qiluvchilar sonini ko‘radi.
Faqat Yuborishni tasdiqlash bosilgandan keyin tarqatiladi. Bekor qilish tarqatmaydi.
Qayta bosilgan tasdiqlash yangi tarqatish boshlamaydi.
Tarqatish alohida oqimda, taxminan soniyasiga 10 xabar bilan bajariladi.
429 xatosida retry_after kutish va chegaralangan qayta urinish mavjud.
Botni bloklagan foydalanuvchi faol emas deb belgilanadi; boshqalarga tarqatish davom etadi.
Botga qayta yozsa foydalanuvchi yana faol bo‘ladi. Faol bo‘lmaganlar o‘tkazib yuboriladi.
Tarqatish tugaganda muvaffaqiyatli, muvaffaqiyatsiz va o‘tkazib yuborilganlar soni yuboriladi.
Tasdiqlangan navbat qayta ishga tushganda davom etadi. Tasdiqlanmagan loyiha yuborilmaydi.
Jarayon aynan yuborish paytida uzilsa, Telegram yetkazganini aniqlab bo‘lmaydi:
takror yubormaslik uchun noaniq qabul qiluvchi o‘tkazib yuboriladi deb hisoblanadi.
Tarmoq uzilishida ayrim xabar yetkazilgan bo‘lsa ham muvaffaqiyatsiz hisoblanishi mumkin.
Tasdiqlangan tarqatishni oddiy Bekor qilish tugmasi to‘xtatmaydi.

SAQLASH VA TEKSHIRUV
movies.db o‘chirilmasin. Eski movies/state/sources jadvallari saqlanadi.
Yangi ustun va jadvallar bot ishga tushganda avtomatik qo‘shiladi.
Foydalanuvchilar, admin bosqichlari, so‘ralgan kino, sozlamalar va navbat bazada saqlanadi.
Eski versiya foydalanuvchilarni saqlamagan: jami foydalanuvchilar endi qayd qilinganlardan hisoblanadi.
Statistika muvaffaqiyatli kino yuborishlarini ko‘rsatadi, qurilmaga yuklab olishlarni emas.
Ko‘p bosqichli oynalarda Orqaga/Bekor qilish yoki /back va /cancel ishlaydi.
Zaxira olish uchun botni to‘xtatib movies.db faylini nusxalang.
Bir token va bitta baza bilan faqat bitta bot nusxasini ishga tushiring.
Webhook o‘rnatilgan bo‘lsa, pollingdan oldin uni o‘chirish kerak.
Mock tekshiruvlar: python -m unittest discover -s tests -v
Testlar vaqtinchalik bazada ishlaydi va haqiqiy Telegramga xabar yubormaydi.
Haqiqiy muhitda kanal huquqlari, ochiq/yopiq obuna, file_id, kanal xabari va tugmalarni tekshiring.
Telegram API: https://core.telegram.org/bots/api
Tarqatish cheklovlari: https://core.telegram.org/bots/faq#how-can-i-message-all-of-my-bots-subscribers-at-once
