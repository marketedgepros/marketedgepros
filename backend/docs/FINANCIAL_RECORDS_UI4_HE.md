# ארנק ומשיכות — מסכי UI-4 וגבול פדיון

## היקף

שלוש הכתובות הקיימות `/wallet`, `/trader/withdrawals`, `/admin/withdrawals` מציגות רשומות legacy לקריאה בלבד, בשפת navy/cyan, עם מעטפת נתב אחת, טבלאות נגללות בתוך מכולה ומצבי טעינה/כשל/ריק/ארנק חסר נפרדים. אין בקשת משיכה, אישור, דחייה, סימון תשלום או ייצוא נתונים פיננסיים במסכים אלה. אין צ׳אט צף שמכסה נתונים.

כל תגובת קריאה כוללת `owner_context` מה־principal, `balance_verification=unverified_legacy`, `payouts_enabled=false`, `available_for_payout=null`, `currency=null`. סכומי Decimal מחרוזות מדויקות או null; לא מחושבת יתרה כוללת, לא מונח USD/USDT ולא מוצגת זכאות. סטטוס completed היסטורי אינו אישור העברה. היעדר ארנק הוא 404 קנוני `WALLET_NOT_FOUND` עם reason `unverified_legacy`; לא יוצרים ארנק בקריאה ולא מציגים אפס כתחליף.

## קריאה ופרטיות

- `/api/v1/wallet/balance`: ארנק המשתמש והמותג הנוכחיים, ללא aggregate של יתרות.
- `/api/v1/wallet/transactions`: עמוד רשומות של אותו ארנק; filter balance_type, סדר created_at DESC NULLS LAST ו־id DESC.
- `/api/v1/traders/withdrawals`: רשומות בעלים ישיר או Agent עם User תואם; שני שדות בעלות חייבים להתאים. challenge שאינו NULL חייב להיות של אותו בעלים ו־program tenant. אין הסקת בעלים מאתגר.
- `/api/v1/wallet/admin/withdrawals` ו־`admin/wallets`: root מפורש או תחימת היררכיה מלאה קיימת; לא רשימת כל הלקוחות מכוח תפקיד בלבד.

תגובות מצומצמות לרשימת שדות מפורשת; אין שמות/אימיילים, פרטי בנק/כתובת ארנק, transaction_id, notes או טקסט פרטי חופשי. tenant חיובי נדרש לפני SQL משאב. unknown/duplicate/noncanonical query נדחה; page 1..10000, per_page 1..50 (ברירת מחדל 20), offset <=10000. הספירה והעמוד צריכים להגיע מאותו snapshot, גם כשאין שורות מעבר לסוף; אין רשימה בלתי־מוגבלת או ניחוש total. PG statement_timeout=1500ms ו־no-autoflush נשמרים.

## סמכות תצוגה

הלקוח מאמת owner_context מול זהות עצמאית מה־store, wallet.user_id ו־row wallet/user ID, שדות exact, דגלים, Decimal/date, pagination/cardinality/unique IDs והמסנן שהתבקש. כשל חוזה אינו רשימה ריקה. key לפי auth/id/tenant/role/query מונע הצגת מידע קודם עוד לפני effect; AbortSignal מועבר ל־Axios. רענון session באותו principal אינו GET חדש. כל GET פיננסי משתמש `_skipAuthRefresh=true`: אין refresh/replay אוטומטי אחרי 401. רענון מסך מפורש בלבד, ללא polling.

## חסימת פדיון לא מאומת

`POST /api/v1/traders/withdrawals`, פעולות wallet admin הקיימות, כל כניסות `/api/payouts` וכל שמונה המתודות הציבוריות של `PayoutService` מסרבים ב־503 `WALLET_LEDGER_NOT_CONFIGURED` לפני קריאת גוף/משאב/שינוי יתרה. JWT/admin/CSRF נבדקים לפי הנתיב תחילה. אין reservation, הודעה, חתימת ארנק או provider. חתימות השירות נשמרו; אין מחיקה או שכתוב של רשומות היסטוריות ואין מיגרציה חדשה בחבילה.

## אימות וגבולות

בדיקות HTTP במפעל Flask האמיתי ובדיקות PostgreSQL/Redis מבודדים משתמשות בנתונים סינתטיים בלבד; הזריעה נצמדת לסכמה שנבנתה ב־Alembic head, כולל עמודות legacy לא־ממופות, בלי לשנות מודלים/מיגרציות היסטוריים. snapshot raw מוכיח שימור רשומות ויתרות; ממפי frontend מוצלבים עם תגובות HTTP אלה. בדיקות React/App/נתב מאמתות זהות, מסנן, דפדוף, כשל והרשאות בנייד ובדסקטופ. ביקורת, תיקוניה ו־CI לפי SHA מדויק בדוח המסירה — לא אישור ייצור.

זהו סיום מסכי כסף במצב מוגן, **לא** מסלול משיכות חי. להפעלת כסף נדרשים מקור ledger/settlement ומסחר מאומתים, החלטות מוצר, provider אמיתי ואישור העברה. יתר מסכי UI-4, UI-5/6 והכרעות UI-3 נשארים במעקב. אין merge/deploy בחבילה.
