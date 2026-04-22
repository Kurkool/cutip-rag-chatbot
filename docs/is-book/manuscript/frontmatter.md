# Front Matter — VIRIYA IS

<!-- ไฟล์นี้รวมหน้าต้นของเล่ม IS ทั้งหมด ในการ export จะถูกแยกเป็นหน้าแต่ละส่วน -->

## ปกภาษาไทย

<div style="text-align: center; margin-top: 150px;">

[LOGO: VIRIYA icon mark — `docs/logo/viriya-icon-mark.svg`]

**การพัฒนาระบบผู้ช่วยตอบคำถามหลักสูตรอัตโนมัติผ่าน LINE Official Account
ด้วยเทคโนโลยี Retrieval-Augmented Generation (RAG)
เพื่อเพิ่มประสิทธิภาพการบริการการศึกษาและลดภาระงานเจ้าหน้าที่**

นายเกอกุล อัศวดิสัยยังกูล

รหัสประจำตัวนิสิต 6780016820

สารนิพนธ์นี้เป็นส่วนหนึ่งของการศึกษาตามหลักสูตรปริญญาวิทยาศาสตรมหาบัณฑิต
สาขาวิชาธุรกิจเทคโนโลยีและการจัดการนวัตกรรม (สหสาขาวิชา)
สหสาขาวิชาธุรกิจเทคโนโลยีและการจัดการนวัตกรรม
บัณฑิตวิทยาลัย จุฬาลงกรณ์มหาวิทยาลัย
ปีการศึกษา 2568

ลิขสิทธิ์ของจุฬาลงกรณ์มหาวิทยาลัย

</div>

---

## ปกภาษาอังกฤษ (TITLE PAGE — English)

<div style="text-align: center; margin-top: 150px;">

[LOGO: VIRIYA icon mark]

**DEVELOPMENT OF AN INTELLIGENT CURRICULUM Q&A ASSISTANT ON LINE OFFICIAL ACCOUNT
USING RETRIEVAL-AUGMENTED GENERATION (RAG) TECHNOLOGY
FOR EDUCATIONAL SERVICE EFFICIENCY AND STAFF WORKLOAD REDUCTION**

Mr. Kurkool Ussawadisayangkool

Student ID 6780016820

An Independent Study Submitted in Partial Fulfillment of the Requirements
for the Degree of Master of Science in
Technopreneurship and Innovation Management
Inter-Department of Technopreneurship and Innovation Management
Graduate School
Chulalongkorn University
Academic Year 2025

Copyright of Chulalongkorn University

</div>

---

## หน้าอนุมัติ (APPROVAL PAGE)

<div style="text-align: center;">

**หัวข้อสารนิพนธ์** การพัฒนาระบบผู้ช่วยตอบคำถามหลักสูตรอัตโนมัติผ่าน LINE Official Account
ด้วยเทคโนโลยี Retrieval-Augmented Generation (RAG)
เพื่อเพิ่มประสิทธิภาพการบริการการศึกษาและลดภาระงานเจ้าหน้าที่

**โดย** นายเกอกุล อัศวดิสัยยังกูล

**สาขาวิชา** ธุรกิจเทคโนโลยีและการจัดการนวัตกรรม (สหสาขาวิชา)

**อาจารย์ที่ปรึกษาหลัก** อ.นกุล คูหะโรจนานนท์

</div>

บัณฑิตวิทยาลัย จุฬาลงกรณ์มหาวิทยาลัย อนุมัติให้นับสารนิพนธ์ฉบับนี้เป็นส่วนหนึ่งของการศึกษาตามหลักสูตรปริญญาวิทยาศาสตรมหาบัณฑิต

**คณะกรรมการสอบสารนิพนธ์**

_____________________________________ ประธานกรรมการ

(_____________________________________)

_____________________________________ อาจารย์ที่ปรึกษาหลัก

(อ.นกุล คูหะโรจนานนท์)

_____________________________________ กรรมการ

(_____________________________________)

---

## บทคัดย่อภาษาไทย

**เกอกุล อัศวดิสัยยังกูล** : การพัฒนาระบบผู้ช่วยตอบคำถามหลักสูตรอัตโนมัติผ่าน LINE Official Account ด้วยเทคโนโลยี Retrieval-Augmented Generation (RAG) เพื่อเพิ่มประสิทธิภาพการบริการการศึกษาและลดภาระงานเจ้าหน้าที่ อ.ที่ปรึกษาหลัก: อ.นกุล คูหะโรจนานนท์

การศึกษานี้มีวัตถุประสงค์เพื่อพัฒนาและประเมินระบบผู้ช่วยตอบคำถามหลักสูตรอัตโนมัติในชื่อ VIRIYA ที่ใช้เทคโนโลยี Retrieval-Augmented Generation (RAG) ร่วมกับสถาปัตยกรรม Multi-tenant Software-as-a-Service บนแพลตฟอร์ม LINE Official Account สำหรับหลักสูตรระดับบัณฑิตศึกษาของจุฬาลงกรณ์มหาวิทยาลัย การวิจัยแบ่งเป็นสามขั้นตอน ได้แก่ การศึกษาและทำความเข้าใจปัญหาผ่านการสัมภาษณ์เชิงลึกเจ้าหน้าที่หลักสูตร 4 ท่านและนิสิต 3 ท่าน การพัฒนาระบบด้วยแนวทาง iterative development และ test-driven development และการประเมินระบบกับผู้ใช้งานจริงในสี่รูปแบบ

ผลการศึกษาพบว่าระบบ VIRIYA สามารถตอบคำถามในระดับ deploy-ready ที่สัดส่วน 50% (7 จาก 14 คำถามที่ผู้ประเมินสองท่านทดสอบ) คำตอบที่ทำได้ดีครอบคลุมกระบวนการทางวิชาการ เช่น การสอบวิทยานิพนธ์และเกณฑ์การประเมิน ขณะที่ข้อมูลที่ต้องอัปเดตบ่อย เช่น ตารางเรียนและประกาศทุน ยังเป็นจุดที่ต้องปรับปรุง ผลการสำรวจการยอมรับเทคโนโลยีตามกรอบ TAM ของนิสิตกลุ่มตัวอย่าง 6 ท่าน พบค่าเฉลี่ยสูงกว่า 4.20 จากสเกล 5 ในทุก construct (PU 4.25, PEOU 4.33, Credibility 4.22, Intention 4.22) สะท้อนแนวโน้มการยอมรับในระดับสูง ผู้ประเมินเจ้าหน้าที่ประมาณการว่าระบบช่วยประหยัดเวลาการตอบคำถามซ้ำได้ประมาณ 14-17 ชั่วโมงต่อสัปดาห์ การวิเคราะห์ความเป็นไปได้ทางการเงินแสดงว่าธุรกิจในรูปแบบ B2B SaaS สามารถคืนทุนได้ในระยะ 11-12 เดือนภายใต้สมมติฐานการเพิ่มลูกค้า 2 ราย/เดือนและโครงสร้างค่าบริการสามระดับ

| สาขาวิชา | ธุรกิจเทคโนโลยีและการจัดการนวัตกรรม (สหสาขาวิชา) | ลายมือชื่อนิสิต ______________________ |
|---|---|---|
| ปีการศึกษา | 2568 | ลายมือชื่อ อ.ที่ปรึกษาหลัก ______________________ |

---

## บทคัดย่อภาษาอังกฤษ (ABSTRACT)

**Kurkool Ussawadisayangkool**: Development of an Intelligent Curriculum Q&A Assistant on LINE Official Account using Retrieval-Augmented Generation (RAG) Technology for Educational Service Efficiency and Staff Workload Reduction. Advisor: Dr. Nagul Cooharojananone

This independent study aims to develop and evaluate VIRIYA, an intelligent curriculum Q&A assistant that combines Retrieval-Augmented Generation (RAG) technology with a Multi-tenant Software-as-a-Service architecture on the LINE Official Account platform for graduate programs at Chulalongkorn University. The research was conducted in three phases: (1) exploration of stakeholder problems through in-depth interviews with 4 program staff and 3 graduate students, (2) system development using iterative development and test-driven development methodologies, and (3) evaluation with real users across four modalities including chatbot quality assessment, admin portal usability tasks, TAM survey, and post-evaluation in-depth interviews.

Results show that VIRIYA achieves a 50% deploy-ready rate (7 of 14 test questions across two evaluators), performing well on academic process questions (thesis examinations, evaluation criteria) while showing gaps on frequently-updated information (class schedules, scholarship announcements). Technology Acceptance Model (TAM) survey results from 6 graduate students indicate high acceptance with all constructs scoring above 4.20 out of 5 (Perceived Usefulness 4.25, Perceived Ease of Use 4.33, Credibility 4.22, Intention to Use 4.22). Staff evaluators estimate time savings of approximately 14-17 hours per week on repetitive queries. Financial feasibility analysis indicates the business can achieve break-even within 11-12 months under a baseline scenario with 2 new customers per month and a three-tier subscription pricing structure. The study contributes a working reference architecture for multi-tenant RAG systems in Thai higher education, along with empirical data on user acceptance and commercial viability.

| Field of Study | Technopreneurship and Innovation Management | Student's Signature ______________________ |
|---|---|---|
| Academic Year | 2025 | Advisor's Signature ______________________ |

---

## กิตติกรรมประกาศ (ACKNOWLEDGEMENTS)

สารนิพนธ์ฉบับนี้สำเร็จลุล่วงได้ด้วยความอนุเคราะห์จากบุคคลและหน่วยงานที่ผู้วิจัยขอกราบขอบพระคุณ

ขอขอบพระคุณอาจารย์นกุล คูหะโรจนานนท์ อาจารย์ที่ปรึกษาหลัก ที่ให้คำแนะนำในทุกขั้นตอนของการศึกษาและเปิดโอกาสให้ผู้วิจัยได้พัฒนาระบบในทิศทางที่สอดคล้องกับความสนใจส่วนตัว ตั้งแต่การกำหนดขอบเขตการศึกษา การออกแบบสถาปัตยกรรม การประเมินผล จนถึงการเขียนสารนิพนธ์ฉบับนี้

ขอขอบพระคุณอาจารย์กวิน อัศวานันท์ ผู้อำนวยการหลักสูตร CU-TIP ที่เปิดโอกาสให้นำระบบมาทดสอบในหลักสูตร และเจ้าหน้าที่หลักสูตรทุกท่านที่สละเวลาให้สัมภาษณ์เชิงลึกและทดลองใช้ระบบ รวมทั้งให้ข้อเสนอแนะที่เป็นประโยชน์ต่อการปรับปรุงระบบในหลายด้าน

ขอขอบคุณเจ้าหน้าที่หลักสูตรสหสาขาวิชาการจัดการสารอันตรายและสิ่งแวดล้อมและหลักสูตรสหสาขาวิชาวิทยาศาสตร์สิ่งแวดล้อมที่ให้ความร่วมมือในการสัมภาษณ์เชิงลึกและช่วยให้ผู้วิจัยเข้าใจบริบทของการให้บริการข้อมูลหลักสูตรที่หลากหลายในระดับบัณฑิตศึกษา

ขอขอบคุณนิสิตในหลักสูตร TIP ที่สละเวลาให้สัมภาษณ์เชิงลึกและตอบแบบสอบถามการยอมรับเทคโนโลยี ข้อคิดเห็นจากนิสิตเป็นจุดเริ่มต้นของการออกแบบระบบที่ตอบโจทย์ผู้ใช้งานจริง

ในการพัฒนาเนื้อหาและการจัดทำเล่มสารนิพนธ์นี้ ผู้วิจัยได้ใช้ระบบปัญญาประดิษฐ์ Claude (Anthropic) เป็นเครื่องมือเสริมในการวิเคราะห์ข้อมูลสัมภาษณ์ การเรียบเรียงเนื้อหาในเบื้องต้น การตรวจสอบการอ้างอิง และการแปลเนื้อหาระหว่างภาษาไทยและภาษาอังกฤษ ภายใต้การควบคุมและการแก้ไขของผู้วิจัยตามหลักการใช้ AI อย่างรับผิดชอบในงานวิจัย รายละเอียดการใช้งานและกฎเกณฑ์ที่ใช้ควบคุมคุณภาพของเนื้อหาปรากฏในภาคผนวก ฉ

สุดท้ายนี้ ผู้วิจัยขอขอบพระคุณครอบครัวและเพื่อนร่วมงานที่เข้าใจและสนับสนุนในระหว่างการศึกษา ทำให้การศึกษานี้สำเร็จลุล่วงได้ตามเป้าหมาย

---

## สารบัญ (TABLE OF CONTENTS)

[TOC: จะ auto-generate จาก heading ของแต่ละบทตอน export ด้วย python-docx — ระบุตั้งแต่ Abstract จน Biography ตามโครงสร้างของคู่มือการพิมพ์วิทยานิพนธ์จุฬาฯ 2548]

- บทคัดย่อภาษาไทย
- บทคัดย่อภาษาอังกฤษ
- กิตติกรรมประกาศ
- สารบัญ
- สารบัญตาราง
- สารบัญภาพ
- บทที่ 1 บทนำ
- บทที่ 2 ทบทวนวรรณกรรมและงานวิจัยที่เกี่ยวข้อง
- บทที่ 3 วิธีการดำเนินการวิจัย
- บทที่ 4 ผลการทำวิจัยและการวิเคราะห์ข้อมูล
- บทที่ 5 การศึกษาความเป็นไปได้ของผลิตภัณฑ์เชิงธุรกิจ
- บทที่ 6 การศึกษาความเป็นไปได้ทางการเงิน
- บทที่ 7 สรุปผลงานวิจัย อภิปราย และข้อเสนอแนะ
- บรรณานุกรม
- ภาคผนวก ก แบบสอบถามการยอมรับเทคโนโลยี (TAM)
- ภาคผนวก ข ชุดคำถามการสัมภาษณ์เชิงลึก (เจ้าหน้าที่และนิสิต)
- ภาคผนวก ค คู่มือการสัมภาษณ์เชิงลึกหลังการประเมิน
- ภาคผนวก ง รายการเอกสารในฐานความรู้ของระบบ
- ภาคผนวก จ รายการชุดทดสอบสำหรับการประเมินคุณภาพคำตอบ
- ภาคผนวก ฉ การใช้ระบบปัญญาประดิษฐ์ในการจัดทำสารนิพนธ์
- ประวัติผู้เขียนสารนิพนธ์
