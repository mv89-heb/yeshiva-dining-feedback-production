# מערכת משוב לחדר האוכל בישיבה

מערכת Flask עם ממשק תלמידים באנגלית, לוח בקרה למנהלים, Google OAuth ואחסון PostgreSQL.

## קבצים
- `app.py` — שרת Flask, מודל הנתונים, אימות Google וסטטיסטיקות.
- `requirements.txt` — ספריות Python.
- `render.yaml` — הגדרת פריסה ב-Render.
- `templates/` — תבניות HTML.

## פריסה מומלצת: Render + Neon + Google OAuth

### 1. יצירת מסד נתונים קבוע
1. פתחו חשבון ב-Neon וצרו פרויקט PostgreSQL.
2. העתיקו את מחרוזת החיבור (Connection string) של PostgreSQL.
3. שמרו אותה כמשתנה `DATABASE_URL` ב-Render. אם Neon מציג מחרוזת `postgresql://...`, האפליקציה מתאימה אותה ל-driver של psycopg.
4. השתמשו בכתובת החיבור המאובטחת (SSL) שסופקה על ידי Neon. אל תכניסו אותה לקוד או ל-GitHub.

### 2. הגדרת Google OAuth
1. פתחו את Google Cloud Console: https://console.cloud.google.com/
2. צרו פרויקט ובחרו APIs & Services → OAuth consent screen.
3. הגדירו את מסך ההסכמה ואת פרטי האפליקציה. בזמן בדיקות, הוסיפו את חשבונות הבדיקה כ-Test users אם Google דורש זאת.
4. ב-APIs & Services → Credentials צרו OAuth Client ID מסוג Web application.
5. ב-Authorized JavaScript origins הוסיפו את כתובת Render, למשל `https://your-service.onrender.com`.
6. ב-Authorized redirect URIs הוסיפו בדיוק: `https://your-service.onrender.com/auth/google/callback`.
7. שמרו את Client ID ואת Client Secret.

### 3. יצירת שירות ב-Render
1. דחפו את הקבצים ל-GitHub.
2. ב-Render בחרו New → Web Service וחברו את המאגר.
3. אפשר להשתמש ב-`render.yaml` כ-Blueprint, או להגדיר ידנית:
   - Build command: `pip install -r requirements.txt`
   - Start command: `gunicorn --workers 2 --threads 4 --timeout 30 app:app`
4. הגדירו משתני סביבה:
   - `SECRET_KEY`: מפתח אקראי ארוך. Render יכול ליצור אותו אוטומטית.
   - `DATABASE_URL`: מחרוזת החיבור של Neon.
   - `GOOGLE_CLIENT_ID`: ה-Client ID של Google.
   - `GOOGLE_CLIENT_SECRET`: ה-Client Secret של Google.
   - `GOOGLE_REDIRECT_URI`: `https://your-service.onrender.com/auth/google/callback`
   - `ADMIN_EMAILS`: רשימת כתובות Google מורשות, מופרדות בפסיקים, למשל `admin@example.org,manager@example.org`
   5. בצעו Deploy.

### 4. בדיקות
- `https://your-service.onrender.com/` — טופס התלמידים.
- `https://your-service.onrender.com/admin/login` — כניסת מנהלים דרך Google.
- `https://your-service.onrender.com/health` — בדיקת תקינות ומסד נתונים.
- ודאו שכתובת המנהל נמצאת בדיוק ב-`ADMIN_EMAILS` ושהחשבון מאומת ב-Google.

## פיתוח מקומי
צרו סביבה וירטואלית והתקינו `requirements.txt`. הגדירו `SECRET_KEY`, פרטי Google OAuth, `ADMIN_EMAILS` ו-`DATABASE_URL`. אפשר להשמיט `DATABASE_URL` בפיתוח מקומי כדי להשתמש בקובץ SQLite מקומי. כתובת callback מקומית היא `http://127.0.0.1:5000/auth/google/callback`; יש להוסיף אותה ל-Authorized redirect URIs ב-Google OAuth.

## אבטחה ותפעול
- אין לשמור סודות ב-GitHub.
- רק כתובות שנמצאות ב-`ADMIN_EMAILS` יכולות להיכנס ללוח הבקרה.
- מסד הנתונים נוצר אוטומטית בהפעלה הראשונה. `create_all()` אינו כלי לניהול שינויים מורכבים בסכמה; לפני שינויי סכמה עתידיים יש להוסיף migrations.
- שירות Render חינמי עשוי להיכנס למצב שינה ולעלות לאט בבקשה הראשונה. מסד הנתונים ב-Neon הוא רכיב נפרד; בדקו את מגבלות ותנאי התוכנית החינמית העדכניים של הספקים לפני שימוש קריטי.
- Tailwind CDN נוח להתחלה; למערכת ארוכת טווח מומלץ לבנות CSS סטטי.
