# แชตบอตเทศบาลเมืองศิลา

## ลองหน้าแชตบนเครื่อง

เปิด PowerShell ในโฟลเดอร์ `ChatBotCola` แล้วรัน

```powershell
cd BackEnd_ChatBot
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m uvicorn preview:app --host 127.0.0.1 --port 8765
```

เปิด [หน้าแชต](http://127.0.0.1:8765/) แล้วลองถามว่า “ติดต่อเทศบาลเมืองศิลาได้ทางไหนบ้าง” โหมดทดลองใช้ข้อมูลติดต่อและลิงก์บริการจากเว็บไซต์เทศบาล ประวัติแชตและหน้าเจ้าหน้าที่ต้องใช้ระบบจริง

## เชื่อม Supabase และ Gemini

คัดลอก `.env.example` เป็น `.env` ในโฟลเดอร์หลังบ้าน แล้วตั้งค่าตามตัวอย่าง ใช้ Supabase URL และ service-role key ของโปรเจกต์เดิม ใส่ Gemini API key และสร้าง `SESSION_SECRET` ใหม่สำหรับสภาพแวดล้อมนี้ ตั้งชื่อผู้ใช้และรหัสผ่านเจ้าหน้าที่ในไฟล์เดียวกัน เก็บไฟล์นี้ไว้เฉพาะในเครื่องหรือในระบบจัดการ secrets ของโฮสต์

รัน API จริงจากโฟลเดอร์หลังบ้าน

```powershell
.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```

เปิด PowerShell อีกหน้าต่างจากโฟลเดอร์ `ChatBotCola` เพื่อรันหน้าเว็บ

```powershell
cd FrontEnd_ChatBot
python -m http.server 5173 --bind 127.0.0.1
```

ตรวจ [health endpoint](http://127.0.0.1:8000/health) แล้วลองเข้าสู่ระบบจาก [หน้าเจ้าหน้าที่](http://127.0.0.1:5173/login.html) ระบบใช้ตาราง `documents`, `chat_sessions`, `chat_messages`, `chat_analytics`, ฟังก์ชัน `match_documents` และ Storage bucket เดิม

## OCR และการนำเอกสารเข้า

อัปโหลด PDF จากหน้าเจ้าหน้าที่ ระบบอ่านชั้นข้อความเป็นรายหน้าและใช้ Tesseract ภาษาไทยกับอังกฤษสำหรับหน้าที่เป็นภาพสแกน หากรันบน Windows ให้ติดตั้ง Tesseract และไฟล์ภาษา `tha.traineddata` กับ `eng.traineddata` แล้วตั้ง `TESSDATA_PREFIX` เป็นโฟลเดอร์ `tessdata` ส่วน Dockerfile ติดตั้งทั้งสองภาษาให้แล้ว

หลังอัปโหลด ลองถามด้วยข้อมูลที่อยู่ในเอกสารและตรวจชื่อเอกสารกับเลขหน้า หากเอกสารยาว ให้เริ่มจากชุดเล็ก เพราะ OCR และการทำดัชนีใช้เวลาตามจำนวนหน้า งานอัปโหลดทำในคำขอเดียวและขึ้นอยู่กับ timeout ของโฮสต์

## นำขึ้น Render

Render Free ใช้ Dockerfile เพื่อรันหน้าเว็บ, API และ OCR จากโดเมนเดียวกัน โดยเก็บเอกสารและฐานข้อมูลใน Supabase เดิม

1. รัน `python stage_web.py` จากโฟลเดอร์หลังบ้านก่อนประกอบรุ่นที่จะเผยแพร่ แล้วตรวจไฟล์ที่สร้างใน `web/` ให้ตรงกับหน้าเว็บล่าสุด สร้าง commit ที่รวม `web/` และ `render.yaml` ใน branch สำหรับดีพลอย
2. ใน Render เลือก **New → Blueprint** เชื่อม repo หลังบ้านและเลือก branch ที่เตรียมไว้ Blueprint กำหนด Docker, แผน Free, health check ที่ `/health` และสร้าง `SESSION_SECRET` ให้
3. ตั้ง `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `ADMIN_USERNAME` และ `ADMIN_PASSWORD` ใน Render ตรวจชื่อ Storage bucket เดิมและแก้ `SUPABASE_BUCKET` ถ้าต่างจาก `pdfs`
4. Blueprint ใช้ `AI_PROVIDER=cloudflare` ตั้ง `CLOUDFLARE_ACCOUNT_ID` และ `CLOUDFLARE_API_TOKEN` ที่จำกัดสิทธิ์เฉพาะ Workers AI ใน Render Dashboard เลือก Workers Free ใน Cloudflare ใช้โควตาฟรีตามบัญชี และไม่ต้องผูก Google Cloud Billing
5. เมื่อ deploy ผ่าน ให้เปิด URL จากอุปกรณ์อื่นและทดสอบตามรายการด้านล่าง บริการ Docker, Supabase และโมเดลรันบนคลาวด์หลังปิดเครื่องได้

สำหรับโหมดทดสอบแบบจำกัดผู้ใช้ที่เข้าเงื่อนไข Gemini Developer API ให้ตั้ง `AI_PROVIDER=gemini` และ `GEMINI_API_KEYS` ในสภาพแวดล้อมนั้น ใช้ข้อมูลสังเคราะห์หรือเอกสารสาธารณะที่ตรวจแล้ว Gemini Developer API มีเงื่อนไขเรื่องกลุ่มผู้ใช้อายุต่ำกว่า 18 ปี จึงต้องใช้บริการ AI ภายใต้เงื่อนไขที่เทศบาลตรวจแล้วสำหรับการเปิดสาธารณะ

ดัชนี Cloudflare ใช้เวกเตอร์ BGE-M3 1,024 มิติแยกจากดัชนีเดิม รัน `supabase/cloudflare_vectors.sql` ก่อน หลังตรวจว่าไฟล์เป็นเอกสารสาธารณะของเทศบาล ใช้ `python backfill_cloudflare_vectors.py --source "<รหัส source>"` เพื่อตรวจจำนวนรายการ และเติม `--apply` เฉพาะแหล่งที่ผ่านการตรวจแล้ว การถามตอบจะครอบคลุมเฉพาะเอกสารที่สร้างเวกเตอร์สำหรับผู้ให้บริการที่เลือก เอกสารที่อัปโหลดขณะใช้ Cloudflare จะต้องสร้างเวกเตอร์เดิมเพิ่มหากสลับกลับไป Gemini หรือ Vertex

Workers Free ให้โควตา 10,000 Neurons ต่อวันร่วมกันทั้งบัญชี โทเค็นในหน้าเจ้าหน้าที่แสดงตามที่โมเดลรายงาน ส่วน Neurons ตรวจได้ใน Cloudflare Dashboard

Render Free พักหลังไม่มีทราฟฟิก 15 นาทีและอาจใช้ประมาณหนึ่งนาทีเพื่อเริ่มใหม่ ใช้สำหรับทดสอบนำร่อง ถ้าต้องการให้บริการตอบได้สม่ำเสมอ ให้เลือกแผน always-on ตามภาระจริงและทดสอบ OCR ไฟล์ตัวอย่างก่อนเปิดรับงานขนาดใหญ่

[Render Free](https://render.com/docs/free) · [Render Blueprint](https://render.com/docs/blueprint-spec) · [Workers AI REST API](https://developers.cloudflare.com/workers-ai/get-started/rest-api/) · [Workers AI Free allocation](https://developers.cloudflare.com/workers-ai/platform/pricing/)

### ตรวจหลังขึ้นคลาวด์

- รัน `supabase/admin_usage.sql` เพื่อติดตั้งมิเตอร์ในหน้าเจ้าหน้าที่ ระบบเก็บเฉพาะยอดต่อวันตามเวลาไทย ไม่เก็บเนื้อหาคำถามเพื่อการนับนี้ โทเค็นนับเฉพาะที่โมเดลสร้างคำตอบรายงาน และพื้นที่นับเฉพาะ Storage bucket PDF
- ตั้ง `ADMIN_DAILY_QUESTION_LIMIT`, `ADMIN_DAILY_TOKEN_LIMIT` และ `ADMIN_STORAGE_LIMIT_BYTES` หากต้องการแสดงตัวเลขที่เหลือเทียบกับงบที่กำหนด มิเตอร์แสดงยอดวัดได้แม้ไม่ได้ตั้งงบ และจะระบุเมื่อแหล่งข้อมูลยังไม่พร้อม

- รัน `.venv\Scripts\python.exe verify_deployment.py https://YOUR_SERVICE.onrender.com` เพื่อตรวจหน้าเว็บ, health, การจำกัดสิทธิ์หน้าเอกสาร และแชตที่ไม่บันทึกประวัติ เพิ่ม `--question "คำถามจากเอกสาร"` และ `--expected "ข้อความที่ยืนยันจากต้นฉบับ"` เพื่อทดสอบการค้นจริง
- เปิด `/health` และหน้าแชตจากโทรศัพท์ที่อยู่นอกเครือข่ายเครื่องพัฒนา ตรวจ HTTPS และทดสอบอีกครั้งหลังปล่อยให้บริการพัก
- ถามจากชุดคำถามที่เทศบาลมีคำตอบ ตรวจชื่อเอกสาร เลขหน้า ตัวเลขและวันที่ ทดสอบคำถามที่ไม่มีหลักฐาน การถามต่อโดยปิดประวัติ และการแสดงผลเมื่อโควตา Workers AI หมด
- ตรวจว่า Supabase เปิด RLS สำหรับตารางที่เกี่ยวข้องและบัญชี anon อ่านประวัติหรือเอกสารภายในไม่ได้ ไฟล์ `supabase/enable_table_rls.sql` เปิด RLS ให้ตารางที่หลังบ้านเข้าผ่าน service-role ตรวจสิทธิ์ Storage bucket และทดสอบคืนฐานข้อมูลกับ PDF จากสำรองแยกกัน
- ล็อกอินด้วยบัญชีทดสอบ อัปโหลด PDF สแกนที่กำหนดไว้ ตรวจว่าค้นเจอ เปิดเอกสารได้ และลบเฉพาะไฟล์ทดสอบ ตรวจสถิติข้ามเที่ยงคืนและทดสอบว่าแชตตอบได้ในขณะที่สถิติทำงาน
- ยืนยันอายุข้อมูลที่เทศบาลต้องเก็บ ช่องทางขอลบ และนโยบายของผู้ให้บริการ AI ก่อนเปิดให้ประชาชนใช้
