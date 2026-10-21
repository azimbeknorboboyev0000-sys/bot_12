# Serial yuklash

1. Botga `/admin` yuboring, **📺 Seriallar → ➕ Yangi serial**ni bosing.
2. Nom kiriting. Tavsif va posterni yuboring yoki **O‘tkazib yuborish**ni bosing.
3. Bot avtomatik S1 kabi kod yaratadi; 1-mavsum, 1-qismdan boshlaydi.
4. Videolarni ketma-ket yuboring yoki kanaldan forward qiling. Video MIME turidagi document ham qabul qilinadi. Albomdagi har video alohida qism bo‘ladi.
5. Kerak bo‘lsa keyingi qism yoki mavsum raqamini tugmalar orqali o‘zgartiring. Band raqamda almashtirish yoki yuborilgan videoni o‘tkazish taklif qilinadi; qolgan videolar navbatda kutadi.
6. **✅ Yakunlash**ni bosing va serial havolasini oling.

Mavjud serialga davom etish: **📋 Mavjud seriallar → serial nomi → ➕ Yana qism qo‘shish**. Oxirgi mavsumning oxirgi qismidan keyingi raqam olinadi. Boshqa mavsumga o‘tish uchun mavsum raqamini o‘zgartiring.

Bot qayta ishga tushgach `/admin` orqali **Davom ettirish** yoki **Yakunlash**ni tanlang. Yuklash holati, navbat va qismlar SQLite bazada saqlanadi. Asl videolar o‘chirilmaydi yoki serverga yuklab olinmaydi.

Foydalanuvchi `S1` kabi kod yoki serial havolasini yuboradi. Qism havolalari `?start=e1` kabi yaratiladi. Barcha video olish yo‘llari mavjud majburiy obuna tekshiruvidan o‘tadi.

Ishlash modeli: mavjud bitta `getUpdates` polling jarayoni xabarlarni ketma-ket qayta ishlaydi. Albom xabarlari ham shu oqimda keladi. Har admin navbati alohida; qism yozuvi, navbat holati va keyingi raqam bitta SQLite tranzaksiyasida saqlanadi. Telegram xabar IDsi takroriy update yangi qism yaratishiga yo‘l qo‘ymaydi. Bir token bilan bir vaqtning o‘zida bir nechta polling jarayonini ishga tushirmang.

Tekshiruv: `python -m unittest discover -s tests -v`. Testlar vaqtinchalik bazalar va soxta Telegram API bilan ishlaydi; haqiqiy Telegramda sinov uchun alohida serial yarating.
