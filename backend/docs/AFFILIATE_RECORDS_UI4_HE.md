# UI4 — רשומות אפיליאט: חוזה Backend

מסמך זה מתעד את מסלולי הקריאה האישיים הקיימים בלבד:

- `GET /api/v1/affiliate/referrals`
- `GET /api/v1/affiliate/commissions`

השינוי מוגבל ל־read projections של המסלולים הללו ול־read projections המקבילים ב־`GET /api/v1/affiliate/dashboard`; אין שינוי בקישורי affiliate, מסלולי admin, payouts, models, serializers או migrations. רשומות אלו הן **legacy בלתי מאומתות** ואינן סמכות לתשלום, יתרה, משיכה, זהות או settlement.

## אימות והיקף

שני המסלולים נשארים תחת `token_required`; הם מקבלים JWT ב־Bearer או cookie לפי המדיניות הקיימת. מסלול `GET` אינו משנה את מדיניות CSRF של פעולות cookie שאינן GET: `POST /payout` נשאר חסום ללא CSRF תקין.

לפני SQL על משאבי affiliate:

1. ה־query מפוענח באופן קנוני. כל פרמטר לא מוכר, כפול או לא תקין מחזיר `400`:
   ```json
   {"error":"Invalid affiliate records query","code":"AFFILIATE_RECORDS_QUERY_INVALID"}
   ```
2. המשתמש המאומת חייב לקבל `tenant_id` שלם וחיובי. אין הסקה מ־link, referral, program או payout. אחרת מוחזר `403`:
   ```json
   {"error":"User must belong to a tenant","code":"TENANT_CONTEXT_REQUIRED"}
   ```

הקריאות, וכן projections הרשומות של הדשבורד, משתמשות ב־`db.session.no_autoflush`; אינן יוצרות/משנות/מוחקות רשומות, ואינן טוענות את כל ההיסטוריה בזיכרון. ב־PostgreSQL בלבד נקבע `SET LOCAL statement_timeout = '1500ms'` פעם אחת בעסקת הקריאה. אין retry או loop.

## Query string מותר

| פרמטר | ברירת מחדל | תחום תקין |
|---|---:|---|
| `page` | `1` | מספר עשרוני קנוני, `1..10000` |
| `per_page` | `20` | מספר עשרוני קנוני, `1..50` |
| `status` | `null` | ערך יחיד מן allow-list של המסלול |

Allow-list של referrals: `pending`, `converted`, `cancelled`.

Allow-list של commissions: `pending`, `approved`, `paid`, `cancelled`.

למשל `status[]=approved`, `status=approved&status=paid`, `page=01`, `per_page=51` ו־`status=unknown` נדחים. אין `all`, coercion, או duplicate resolution שקט.

## תנאי קוהרנטיות של הרשומות

### Referrals

כל referral מוחזר רק אם תנאי הבעלות וההורים הבאים מתקיימים:

- `affiliate_user_id` של referral הוא המשתמש המאומת;
- `AffiliateLink` של referral שייך לאותו משתמש;
- אם `referred_user_id` אינו `null`, ה־referred user קיים, אינו המשתמש עצמו, ושייך לאותו tenant;
- אם `program_id` אינו `null`, ה־`TradingProgram` קיים ושייך לאותו tenant;
- הסטטוס הוא תווית allow-list.

`referred_user_id = null` ו/או `program_id = null` נשמרים כרשומת מקור היסטורית **לא שלמה**, בלי להמציא parent. הם אינם הוכחת זהות, רכישה, תשלום או זכאות. לעומת זאת, FK שאינו `null` אך הוא self, חסר או זר, link זר/בעלים לא עקבי, program חסר/זר או סטטוס legacy לא מוכר אינם מופיעים.

### Commissions

כל commission כפוף לאותו predicate referral לעיל, ובנוסף:

- `affiliate_user_id` של commission הוא המשתמש המאומת;
- `referral_id` אינו חסר ומצביע ל־referral הקוהרנטי;
- `type` ו־`status` הם תוויות allow-list;
- אם `payout_id` אינו `null`, קיים `AffiliatePayout` שהבעלים שלו הוא אותו משתמש.

לכן payout זר או dangling, referral חסר, וכל parent עצמי/חסר/זר חסומים. `payout_id = null` אינו פותח סמכות לתשלום.

### עקביות dashboard

`recent_referrals` בדשבורד, רשימת referrals, רשימת commissions ו־aggregate העמלות של הדשבורד משתמשים באותו predicate קוהרנטיות: בעל referral/link תואם, allow-list של status/type לפי סוג הרשומה, nullable historical parents כנ"ל, ו־payout בבעלות המשתמש כאשר הוא אינו `null`. לכן רשומה nullable מותרת מופיעה באותה אוכלוסייה בשתי התצוגות; payout זר או dangling אינו משפיע על `total_commission` או על סכומי `pending`/`approved`/`paid`.

מוני link בדשבורד (`clicks`, `conversions`, `total_revenue`) נשארים מוני cache legacy גולמיים ונפרדים מן אוכלוסיית referral/commission הזאת. הם אינם מקור לזכאות, לתשלום או ל־payout.

## תגובות allow-list

שתי התגובות כוללות רק:

```json
{
  "owner_context": {"user_id": 2, "tenant_id": 1},
  "verification": "unverified_legacy",
  "payouts_enabled": false,
  "available_for_payout": null,
  "currency": null,
  "<records>": [],
  "pagination": {"page": 1, "per_page": 20, "total": 0, "pages": 0},
  "filters": {"status": null}
}
```

`<records>` הוא `referrals` או `commissions`. מיון יציב הוא timestamp יורד ואז `id` יורד. `total` נספר על אותו query מסונן, ו־`pages` מחושב שרתית. דף מעבר לטווח מחזיר מערך ריק עם totals אמיתיים.

### שורת referral

המפתחות המדויקים בלבד:

```json
{
  "id": 1,
  "status": "converted",
  "click_date": "2026-10-12T12:00:00",
  "conversion_date": null,
  "purchase_amount": "0.00",
  "commission_amount": null,
  "currency": null
}
```

### שורת commission

המפתחות המדויקים בלבד:

```json
{
  "id": 1,
  "amount": "0.00",
  "type": "one_time",
  "status": "approved",
  "created_at": "2026-10-12T12:00:00",
  "approved_at": null,
  "paid_at": null,
  "currency": null
}
```

ערכים כספיים נמסרים רק כמחרוזות `Decimal` סופיות או `null`; אין float ואין המרת ערך חסר ל־`0`. אין בתגובות `referred_user`, email, שם, IP, user-agent, landing page, payment details, notes, description, מזהי parent או טקסט חופשי.

## בדיקות ממוקדות

- `backend/security_tests/test_ui4_affiliate_records.py`: Flask אמיתי עם JWT, canary SQL, no-autoflush/no-DML, allow-list, PII, `null` לעומת zero, סדר/דפדוף, filters, self/missing/foreign parents, parity dashboard/list ל־nullable historical rows, payout owned/foreign/dangling וגבול CSRF של payout.
- `backend/staging_tests/test_ui4_affiliate_records.py`: PostgreSQL זמני שמופעל על Unix socket ב־runner המבודד; מאמת timeout מקומי, חוזה HTTP, joins ו־no-DML. ה־fixture משחרר FK payout **אך ורק בסכמה הזמנית** כדי לדמות dangling legacy parent; אין שינוי schema או migration.
- `backend/staging_tests/test_ui4_dashboard_reads.py`: PostgreSQL זמני מאמת parity בין dashboard לרשימות, nullable historical referral, וסכומי payout לפי owner בלבד בלי DML.

ה־JUnit מתעד responses HTTP אמיתיות תחת properties:

- `ui4_affiliate_referrals_payload`
- `ui4_affiliate_commissions_payload`

## מסכי הלקוח והפעולות

שלושה מסכים קיימים — `/affiliate/traders`, `/affiliate/commissions`, `/affiliate/reports` — חולקים רכיבי עיצוב navy/cyan וניווט ליעדים קיימים. המסכים keyed לפי auth/user/tenant/role; hook מבטל קריאות מאוחרות לפי זהות, עמוד, מסנן ורענון. אותו principal ברענון session אינו מתחיל GET מחדש. expectedOwner מגיע מהזהות הנוכחית, לא מהתגובה; AbortSignal מגיע ל־Axios.

הלקוח דורש שדות typed, מחרוזות כסף exact/null, תאריכים תקינים ומזהים ייחודיים. cardinality העמוד חייבת להתאים בדיוק ל־page/per_page/total; עמוד חלקי לא צפוי מסרב עם אפשרות רענון מפורשת, לא retry אוטומטי. שורות חייבות להתאים למסנן שנשלח. compatibility mapper של payload מלא גוזר מסנן רק כאשר הקורא לא סיפק אותו; transport תמיד מאמת מול בקשתו המקורית והזהות העצמאית.

Reports מציג רק fields מהדשבורד, בלי השוואה, אחוז שיווקי, מטבע או סכום חלקי מומצאים. הייצוא מוגבל לעמוד העמלות הנוכחי שאומת; אין ייצוא כל ההיסטוריה. ערכים נשמרים כמחרוזות, כותרות כוללות legacy/currency unavailable, נוסחאות עם leading Unicode מנוטרלות ו־DOM/Blob משוחררים גם בכשל. אין create/approve/pay.

מצבי loading/error/empty מובחנים; controls נגישים ומעטפת אחת. בדיקות 320/1440 הראו גלילה פנימית לטבלאות ללא גלישה של כל העמוד. הצ׳אט הצף מוסתר בשלושת המסכים כדי שלא יכסה סכום או שורה, וקישור התמיכה נשמר. בדיקות App סינתטיות, תשובות HTTP אמיתיות ממסד זמני, ביקורת ורגרסיות מתועדות בדוח המסירה; אין אימות ספק, ייצור או פריסה.
