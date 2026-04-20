# EndNote Workflow Sample

ไฟล์ตัวอย่างสำหรับทดสอบ workflow EndNote ก่อนลงแรงเขียน 120 หน้า

## ไฟล์ในโฟลเดอร์นี้

| ไฟล์ | หน้าที่ |
|---|---|
| `verified-refs-sample.ris` | 3 references (RIS format) — Lewis 2020, Davis 1989, Bezemer 2010 |
| `sample-manuscript.docx` | ย่อหน้าตัวอย่าง ใช้ temp citation `{Author, Year #RecNum}` |

## วิธีทดสอบ (ทำตามลำดับ)

### 1. Import references เข้า EndNote library

1. เปิด EndNote desktop app
2. `File` → `Import` → `File...`
3. เลือก `verified-refs-sample.ris`
4. Import Option: **Reference Manager (RIS)**
5. Duplicates: ตามสะดวก
6. Text Translation: **Unicode (UTF-8)**
7. คลิก `Import`

**ตรวจ:**
- มี 3 entries ใหม่ใน library
- คลิกแต่ละ entry — Title / Author / Year / Journal / Pages ต้องตรงกับ `.ris`
- ดู **RecNum** ของแต่ละ entry (column "Record Number" — อาจต้อง enable ใน View > Show Fields)
- ถ้า RecNum ที่ได้ = 1, 2, 3 ตามลำดับ → ตรงกับ `.ris` เป๊ะ ใช้ได้เลย
- ถ้า RecNum ไม่ตรง (เช่นเริ่มจาก 247 เพราะ library มี entries เดิมอยู่แล้ว) → ต้องแก้ `{...}` ใน docx ให้ตรงกับ RecNum จริง

### 2. ทดสอบ Cite While You Write ใน Word

1. เปิด `sample-manuscript.docx` ใน Microsoft Word
2. Tab `EndNote X[Y]` (add-in ที่ติดตั้งไว้)
3. ตรวจ Output Style เป็น **APA 7th** (dropdown ใน EndNote toolbar)
4. คลิก **`Update Citations and Bibliography`** (อาจชื่อ "Update Citations" หรือ "Format Bibliography" ขึ้นกับเวอร์ชัน)

**ตรวจผลลัพธ์ที่คาดหวัง:**
- `{Lewis, 2020 #1}` → กลายเป็น `(Lewis et al., 2020)` หรือตามสไตล์ APA 7
- `{Davis, 1989 #2}` → `(Davis, 1989)`
- `{Bezemer, 2010 #3}` → `(Bezemer & Zaidman, 2010)`
- หลังหัวข้อ "บรรณานุกรม" → EndNote generate formatted bibliography ให้อัตโนมัติ (3 entries เรียงตามตัวอักษร)

**ถ้าผ่าน** → ใช้ workflow นี้กับเล่มจริง, ผมจะเขียน manuscript แบบ `{Author, Year #N}` ทุกจุด + ship `verified-refs.ris`

**ถ้าไม่ผ่าน** — เจอปัญหาไหนก็บอก จะแก้ตาม:
- RecNum ไม่ตรง → ส่ง screenshot EndNote library, ผมจะ update RecNum ใน `.ris`
- `{...}` ไม่ถูกแทนที่ → อาจต้องเปลี่ยน syntax / ลองใช้ "Insert Citation" แบบ manual แทน
- Thai authors ใน future refs ตัวอักษรเพี้ยน → ปรับ encoding หรือ fallback `.enw`

## Fallback ถ้า EndNote workflow ใช้ไม่ได้

**Option A:** Manual insert ใน Word — ผมทิ้ง citation ใน manuscript แบบ `(Lewis et al., 2020)` plain text, user ใช้ "Insert Citation" ของ EndNote add-in ทีละจุด (ช้าแต่ชัวร์)

**Option B:** ไม่ใช้ EndNote เลย — ผมเขียน `references.md` แบบ APA 7 manual, user copy-paste ลงเล่ม (ยืดหยุ่นน้อยสุดแต่ไม่พึ่ง add-in)
