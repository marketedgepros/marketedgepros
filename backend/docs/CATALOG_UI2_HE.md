# קטלוג תוכניות — UI-2

## נקודות קצה ציבוריות

- `GET /api/v1/programs/` מחזיר `{"programs":[...]}`.
- `GET /api/v1/programs/<id>` מחזיר אובייקט תוכנית יחיד, ובו גם `addons`.
- הקריאות **אינן** מקבלות בחירת מותג מ־`Host`, מ־`X-Tenant-ID`, או מפרמטרי query. הן משתמשות רק במותג הפעיל שבבעלות `PLATFORM_ROOT_USER_ID` דרך `get_tenant_from_request`.
- אין fallback למותג ראשון או ברירת־מחדל. מדיניות מטבע חסרה/לא־`USD`, root לא תקין, או שורת קטלוג לא ניתנת לייצוג מחזירים `503` עם `CATALOG_UNAVAILABLE`. לפני root או מדיניות לא זמינים לא נשלפת שורת `TradingProgram`.
- תוכנית חסרה, לא פעילה או של מותג זר מחזירה אותו `404`: `{"error":"Resource not found"}`.

## צורת תוכנית

כל פריט רשימה, וכל אובייקט detail, כולל את מפתחות התאימות:

```json
{
  "id": 10,
  "tenant_id": 1,
  "name": "Example",
  "type": "one_phase",
  "description": null,
  "account_size": "10000.00",
  "profit_target": "10.00",
  "max_daily_loss": "5.00",
  "max_total_loss": "10.00",
  "price": "19.99",
  "profit_split": "80.00",
  "rules": {},
  "is_active": true,
  "currency": "USD",
  "terms": {}
}
```

כל ערך כספי/אחוזי מוצג כמחרוזת עשרונית בדיוק בשתי ספרות. ערך אחוז `0` נשמר כ־`"0.00"`; שדה אופציונלי חסר נשאר `null`. אין המרה ל־float. `type` לא מוגבל לרשימת שלבים: תווית ASCII מודפסת, לא־ריקה ועד 50 תווים נשמרת כדי שה־UI יוכל להשתמש ב־fallback דינמי.

`terms` הוא בדיוק המבנה הקנוני של `snapshot.terms` בהצעת הזמנה:

```json
{
  "name": "Example",
  "type": "one_phase",
  "description": null,
  "payout_mode": "on_demand",
  "account_size": "10000.00",
  "profit_target": "10.00",
  "max_daily_loss": "5.00",
  "max_total_loss": "10.00",
  "profit_split": "80.00",
  "profit_split_percentage": "80.00",
  "minimum_payout_amount": "50.00",
  "rules": {}
}
```

המפתחות העליונים `name`, `type`, `description`, `account_size`, האחוזים ו־`rules` שווים לשדות המתאימים ב־`terms`. `rules` חייב להיות object; הוא אינו אישור לכך שהתנאים נבדקו, חיים, או מחוברים לספק.

ב־detail בלבד, `addons` ממוינים לפי `id` ומכילים:

```json
{
  "id": 20,
  "program_id": 10,
  "name": "No fee",
  "description": null,
  "price": "0.00",
  "price_type": "fixed",
  "benefits": {},
  "is_active": true
}
```

`price_type` הוא `fixed` או `percentage`; מחיר add-on גם הוא מחרוזת בשתי ספרות. רק add-ons פעילים של אותה תוכנית מוחזרים.

## מגבלות ותקינות

- הרשימה והתוספים מוגבלים ל־200 פריטים. השאילתה מבקשת 201 כדי לזהות חריגה; חריגה מחזירה `503` ואינה חותכת תוצאות בשקט.
- כל אובייקט `terms` הקנוני (כולל תיאור וכל rules) מוגבל ל־64 KiB; חריגה מחזירה `503` ואינה מקצרת תנאים.
- רשימה אינה טוענת add-ons (ללא N+1). הרשימה והתוספים ממוינים דטרמיניסטית לפי `id`.
- ב־PostgreSQL מוגדרים `lock_timeout='3s'` ו־`statement_timeout='5s'` גם לפני בדיקת ה־root.
- המספרים נבדקים ללא coercion: אין bool/float/NaN/Infinity, אין מספר שלילי, אין יותר משתי ספרות עשרוניות; `account_size` ו־`price` חייבים להיות חיוביים, ואחוזי התוכנית הם `0..100`.

## התאמה להצעת הזמנה

`program_terms(program)` הוא helper משותף לקטלוג ול־`OrderService`. לכן `snapshot.terms` שנשמר בהצעת quote זהה ל־`terms` שהקטלוג החזיר לאותה שורה. הצעת quote עצמה עדיין דורשת במפורש `ORDER_QUOTES_ENABLED=true` וגם `ORDER_QUOTE_CURRENCY=USD`; קריאת קטלוג לא מפעילה flag, לא משנה שורה, ולא מבצעת settlement/provider/entitlement.

ב־PostgreSQL `OrderService` מאשר את `alembic_version` כ־singleton ורק בשלבים המוכרים `20261011_000006`, `000007`, `000008`, `20261012_000001` (ה־head הנוכחי), ולאחר מכן מאמת את trigger ה־immutable המקורי, גוף הפונקציה וה־origin role. שלב היסטורי ללא trigger תקין נשאר `503` (`ORDER_STORAGE_NOT_READY`).

## סגירת ביקורת והצלבת מקור

PurchaseOrder.to_dict מחזיר user_id/tenant_id משורת ההזמנה, ו־frontend מאמת row+snapshot+משתמש+מותג. HTTP POST/replay/GET נבדקו, משתמש זר נשאר 404. hook קטלוג scoped לזהות authenticated/user/tenant; שינוי הקשר מנקה data מיד ומבטל GET קודם. בדיקת React/Zustand אמיתית A→B באותו נתיב עם GET A מאוחר מאמתת ניקוי ודחיית תשובה ישנה. בדיקת PostgreSQL current-head שומרת catalog/quote סינתטיים ב־JUnit; אותם payloads עוברים mappers frontend ומחזירים אותם מחיר ותנאים, ללא חיוב.

Fixture quote מקבל revision מפורש: ברירת מחדל היסטורית 000006 לשמירת בדיקות ledger000007; רק תרגיל קטלוג בוחר heads. אין שינוי של guard ledger או migration היסטורית. אין תשלום/ארנק/MT5, שינוי אחוזים, תנאי hold או policy חדש.
