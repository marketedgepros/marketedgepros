# חבילת מסחר בתוך UI-4 — אתגרים, היסטוריה ו־Scaling

**עודכן:** 12.10.2026. חבילת קוד ובדיקות בענף `fix/security-foundation-20261011`, PR #1 טיוטה בלבד. אין migration, פריסה, פעולת ארנק או MT5 בחבילה זו.

## מסכים ומקורות

| כתובת | מקור נתונים | פעולות נתמכות |
|---|---|---|
| `/challenges` | `GET /api/v1/challenges/my-challenges` | דפדוף מוגבל, מעבר לפרטי רשומה ולתוכניות |
| `/challenges/:id` | `GET /api/v1/challenges/:id/progress` | קריאה של הרשומה ושל metadata MT5, חזרה לרשימה, retry בכשל |
| `/trader/history` | `GET /api/v1/traders/history` | מסנני symbol/side/close-time בשרת, דפדוף, refresh, ייצוא CSV של העמוד הנוכחי בלבד |
| `/scaling` | `GET /api/v1/scaling/my-progress`, ולמנהל `GET /api/v1/scaling/admin/all-users` | קריאה, refresh ודפדוף scoped; קישור לתמיכה, ללא scale-up |

### אתגרים והקשר הבעלות

תגובות list/progress כוללות `owner_context={user_id,tenant_id}` מתוך המשתמש שאומת בשרת. הלקוח מאמת את הקשר הבעלות ואת `challenge.user_id` לפני התצוגה. wrappers נקשרים סינכרונית ל־auth/id/tenant/role, ובפרטי האתגר גם ל־route ID; ביטול בקשה ושער generation מונעים מתשובה ישנה לשחזר מידע או pending. אין ניחוש מותג מתוך שדה alias.

ה־UI מתאים לתפקידי non-admin המוכרים `trader/affiliate/guest` ולשומר הנתב הקיים; מנהל אינו מקבל bypass לבעלות אישית. `user` אינו תפקיד מוצר תקף ולא משמש fixture מורשה. הרשאות השרת נשארו מקור הסמכות.

### היסטוריית מסחר

תוקן הנתיב הישן `/traders/trading-history` ל־`/traders/history`. מקור הרשומות הוא המודל `Trade`, עם `volume` המקורי, לא שדות `lots/pips` שאינם קיימים. תגובה כוללת trades bounded, pagination, filters, owner_context ו־SQL statistics. כל רשומה ו־aggregate מוגבלים ל־Challenge של המשתמש ול־tenant של TradingProgram; אין admin bypass.

- פרמטרים: `page=1..1000`, `per_page=1..100` (ברירת מחדל 20), symbol עד 20 תווי ASCII מוגדרים והתאמה מדויקת לאחר uppercase, type=`all/buy/sell`, period=`all/today/week/month`.
- פרמטרים זרים/כפולים, leading zeros ומספרים ארוכים נדחים לפני שאילתת משאב. היום לפי UTC; 7/30 ימים לפי זמן השרת; חלונות תחומים גם מלמעלה לזמן השרת. חותמות המקור אינן מאומתות.
- סדר close_time יורד עם NULLS LAST ו־ID כ־tie-breaker. דפדוף מוגבל ו־SQL aggregates בלבד; קריאות `no_autoflush`, ללא טעינת כל הרשומות לצורך חישוב.
- כסף, מחיר ו־volume הם מחרוזות Decimal exact או null. אפס שנרשם נשמר; אם חסרה ראיית profit ברשומה מסוננת, winning/losing/total_profit נותרים null. אין הנחת מטבע דולר: `currency=null`.
- כל מסך מסומן `unverified_legacy`, `provider_authenticated=false`. אלו רשומות לקריאה, לא הוכחת מסחר, תשלום, רווח זמין או זכאות למשיכה.

CSV מכיל רק את העמוד הנוכחי שכבר עבר validation. תאים quoted, quotes escaped, ונוסחאות לאחר whitespace/Unicode control/format/separator/mark מנוטרלות. URL של Blob ו־DOM מנוקים גם בכשל; שינוי זהות/פילטר, טעינה וכשל מבטלים זמינות ייצוא של מידע קודם. אין endpoint export בלתי מוגבל.

### Scaling

כל entrypoints של initialize/update-profit/scale-up/pause/resume חסומים בשירות וב־HTTP לפני שאילתת המשאב, parsing של גוף, flush או כתיבה. JWT/CSRF/admin נבדקים לפי המסלול לפני סירוב `503 SCALING_EVIDENCE_NOT_CONFIGURED`. tiers/eligibility אינם מציגים default policy או החלטת זכאות לא מאומתת.

`my-progress` מחזיר null לרשומה חסרה, ולא תוכנית או יתרה מדומה. קיימת יותר מרשומת legacy אחת לאותו owner: סירוב `409 SCALING_OWNER_CONFLICT`, לא בחירה שרירותית. מנהל רשימה מקבל pagination bounded; root מפורש לפי השומר הקיים, או CRM tenant/downline. affiliate אינו מגיע ל־admin/all-users. אין שינוי היררכיה או סמכות חדשה. בכל projection `is_eligible_for_scaling=false`, `scaling_enabled=false`, מטבע null. eligibility שנשמר בעבר אינו הרשאה להגדלת הון ואינו נכתב מחדש בקריאה.

## תצוגה ובדיקות

navy/cyan, כותרות ורכיבי סטטוס, labels/focus ו־alert/status; טבלאות במכולות גלילה ממוקדות ולא גלישת כל העמוד; מרווחי חשבון עקביים, מעטפת אחת בלבד. נבדקו 320/390/1440px עם נתונים סינתטיים ורשת חיצונית חסומה. כשל/ריק/null/אפס, מעבר זהות ומותג/role/route/filter ובקשות מאוחרות נבדקו בנפרד. התגובות האמיתיות של Flask מ־DB סינתטי הוצלבו מול ממפי frontend. בדיקות PostgreSQL/Redis הן במשאבי runner זמניים בלבד; שגיאת teardown של fixture Redis תוקנה בבידוד client מקומי, לא בהחלשת מוצר.

ביקורת בלתי תלויה מצאה שני חסמי חיבור (Unicode CSV ו־symbol substring); שניהם תוקנו עם רגרסיות וחתימת סגירה ממוקדת. תוצאות הרגרסיות ו־CI לפי ה־SHA המדויק בדוח המסירה. CI ירוק אינו אימות ספק או מוכנות ייצור.

## מה נשאר פתוח

UI-4 כולו אינו מושלם. wallet/withdrawals/notifications/support/affiliate/admin/dashboard וכל יתר הפעולות עדיין דורשים סגירה לפי המפה הקבועה. UI-5/6 ו־policy/תוכן דינמי ב־UI-3 פתוחים. אין API ספק, rule policy מאושר או capital command שמאפשרים scale-up. אין פעולות תשלום, ארנק, MT5, merge או deploy בחבילה זו. תאימות לקוחות חיצוניים למעבר מתגובות legacy ישנות מחייבת בדיקת release לפני הפעלה.
