# מאפייה – חילוץ הזמנה עם AI (מימוש לדוגמה, שיעור 7)

מימוש קטן להשוואה: קריאה **אחת** לשירות AI מצד השרת, פלט מובנה (JSON לפי סכימה), בדיקה של מה שחזר, ומתג כשל מסומן.
אין כאן מפתח. בלי מפתח, הכול רץ כ**הדגמה ללא מודל חי** (mock), והמסך אומר זאת.

## Prerequisites

- Node.js 20 ומעלה (`node --version`).
- רשות: מפתח Gemini API אישי מ-Google AI Studio. בלי מפתח – הדגמה בלבד.

## Install

```
npm install
```

(נדרש רק לקריאה אמיתית. הבדיקה וההדגמה רצות גם בלי `npm install`.)

## Run

1. העתיקו את `.env.example` לקובץ חדש בשם `.env` באותה תיקייה, וכתבו בו את המפתח אחרי `GEMINI_API_KEY=`.
2. הריצו `git status` וודאו ש-`.env` **לא** מופיע ברשימה (הוא ב-`.gitignore`).
3. הפעילו:

```
npm start
```

4. פתחו בדפדפן את `http://localhost:3000`, הדביקו הודעה ולחצו «סכם».

רק נתונים בדויים: בשכבה החינמית Google עשויה להשתמש בתוכן כדי לשפר את המוצרים שלה.

## Test

```
node check.js
```

הבדיקה רצה תמיד במצב הדגמה: בלי רשת ובלי מפתח. הפלט הצפוי:

```
mode: mock (no network, no key)
PASS bakery m1: 4 rolls + 2 cookies at 09:00
PASS bakery m2: 6 rolls at 10:00
PASS bakery m3: no time -> pickup_time null, needs_clarification true
PASS bakery totals: 10 rolls, 5 cookies
PASS valid-order: accepted
PASS missing-time: null + needs_clarification
PASS invalid-quantity: valid JSON with quantity -2 is rejected
PASS invented pickup time is rejected
PASS instruction-in-data: output keeps the schema, nothing else
PASS instruction-in-data: an extra field is rejected
PASS every mock answer is labelled
PASS unknown message in mock: a clear error, no made-up order
PASS AI_FORCE_ERROR=429: 2 retries (waits 1000, 2000 ms), then a clear error
PASS AI_FORCE_ERROR=timeout: 2 retries (waits 1000, 2000 ms), then a clear error
PASS AI_FORCE_ERROR=quota: a daily-quota 429 is not retried
15 of 15 checks passed
```

## Structure

- `server.js` – השרת: מגיש את הממשק ומקבל הודעה ב-`POST /api/order`.
- `src/extract.js` – הקריאה האחת לשירות (רק בצד השרת), ניסיון חוזר מוגבל ומתג הכשל. הקוד שלנו סופר את הניסיונות: בכל ניסיון מותרת בקשת רשת אחת, והספרייה לא מנסה שוב בעצמה.
- `src/schema.js` – החוזה: הסכימה של הזמנה (`customer`, `items`, `quantity`, `pickup_time`, `needs_clarification`).
- `src/validate.js` – בדיקת מה שחזר: מבנה וכללי עסק.
- `src/mock.js` – הדגמה ללא מודל חי: תשובות קבועות להודעות הדוגמה בלבד.
- `src/env.js` – טוען את `.env` לשרת.
- `public/` – הממשק (מה שהדפדפן מקבל). אין בו מפתח.
- `check.js` – הבדיקה.

## Switches (.env)

- `AI_MODE=mock` – תמיד הדגמה, גם כשיש מפתח.
- `AI_FORCE_ERROR=429` (או `503`, `timeout`, `quota`) – כשל מדומה, לבדיקה בלבד. `quota` מדמה מכסה יומית שנגמרה: בלי ניסיון חוזר. מוחקים אחרי הבדיקה.
- `GEMINI_MODEL` – שם המודל. בדקו את הרשימה העדכנית בתיעוד של Google.

## Known limits

- במצב הדגמה מוכרות רק הודעות הדוגמה; הודעה אחרת מקבלת שגיאה ברורה, לא הזמנה מומצאת.
- הקריאה האמיתית לא נבדקה כאן עם מפתח אמיתי. המגבלות (בקשות לדקה וליום) משתנות; ראו את עמוד ה-rate limits של Google.
- אין שמירה של הזמנות (זה בשיעור 8).
