# סיכום הזמנות למאפייה – פרויקט פתיחה לשיעור 4

אפליקציית אינטרנט קטנה: היא מציגה שלוש הזמנות לדוגמה (לא לקוחות אמיתיים),
מסכמת כמה לחמניות ועוגיות הוזמנו, ומסמנת הזמנה שחסרה בה שעת איסוף.

## איך פותחים

לחיצה כפולה על `index.html` פותחת את האפליקציה בדפדפן. אין צורך בהתקנה או בבנייה.

## איך בודקים

בטרמינל, מתוך התיקייה הזו:

```
node check.js
```

הפלט הצפוי:

```
Checking the bakery order summary...
PASS total rolls = 10
PASS total cookies = 5
PASS missing pickup time: m3 only
PASS order m1 can be marked ready
PASS an order that does not exist is not marked
5 of 5 checks passed
```

אין `node` במחשב? פתחו את `check.html` בדפדפן: אותן בדיקות, בלי התקנה.

## הקבצים

| קובץ | מה יש בו |
| --- | --- |
| `index.html` | הדף שרואים בדפדפן |
| `app.js` | מצייר את הדף ומטפל בלחיצה על «סימון כמוכנה» |
| `orders.js` | החישובים: סך הכול, שעת איסוף חסרה, סימון כמוכנה |
| `data.js` | שלוש ההזמנות לדוגמה |
| `checks.js` | הבדיקות עצמן |
| `check.js` | מריץ את הבדיקות בטרמינל |
| `check.html` | מריץ את אותן בדיקות בדפדפן |
| `instructions-template.md` | תבנית לקובץ ההוראות לסוכן (שלב D בשיעור) |
