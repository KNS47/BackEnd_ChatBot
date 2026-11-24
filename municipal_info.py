"""Direct links for municipal services with verified official pages."""

import re

CONTACT_URL = "https://www.sila-kk.go.th/contactus.php?menuid=13"
COMPLAINT_URL = "https://www.sila-kk.go.th/link.php?menuid=11"
COMPLAINT_GUIDE_URL = "https://www.sila-kk.go.th/jFrEFAt4O/page/19716284912632022.pdf#page=1"
GUIDES_URL = "https://www.sila-kk.go.th/pagelist.php?menuid=4"
FORMS_URL = "https://www.sila-kk.go.th/pagelist.php?menuid=47"
NEWS_URL = "https://www.sila-kk.go.th/newslist.php?menuid=84"
COMPLAINT_TOPIC = re.compile(r"ร้องเรียน|ร้องทุกข์")
OTHER_COMPLAINT_PROCESS = re.compile(r"ทุจริต|ประพฤติมิชอบ|อุทธรณ์")
COMPLAINT_FOLLOWUP = re.compile(
    r"(?:แล้ว|ถ้ายื่น|ถ้ากรอกแบบฟอร์ม)?(?:"
    r"(?:ต้อง)?(?:แนบ|ใช้|เตรียม)(?:เอกสาร)?อะไร(?:บ้าง)?|(?:ต้อง)?แนบสำเนาบัตร(?:ประชาชน)?ไหม|"
    r"(?:มี|ต้องเสีย|ต้องจ่าย|เสีย|จ่าย)?(?:ค่าธรรมเนียม|ค่าใช้จ่าย)(?:ไหม|หรือไม่|เท่าไหร่|เท่าไร)?|"
    r"(?:ต้องจ่ายไหม|ฟรีไหม|ใช้เวลากี่วัน|กี่วัน(?:ถึงเสร็จ)?|เสร็จกี่วัน|ตรวจสอบกี่วัน|"
    r"เปิดกี่โมง|ปิดกี่โมง|ไปวันไหน|ยื่นได้กี่โมง|วันเสาร์|วันอาทิตย์|วันหยุด)(?:เปิดไหม|ยื่นได้ไหม)?"
    r")(?:ครับ|ค่ะ|คะ)?[?？]*"
)


def lookup_complaint(question: str, recent_questions: list[str]) -> tuple[str, str] | None:
    question = "".join(question.split())
    if OTHER_COMPLAINT_PROCESS.search(question):
        return None
    if not COMPLAINT_TOPIC.search(question):
        if not COMPLAINT_FOLLOWUP.fullmatch(question):
            return None
        for previous in reversed(recent_questions):
            topic = "".join(previous.split())
            if topic and not COMPLAINT_FOLLOWUP.fullmatch(topic):
                break
        else:
            return None
        if not COMPLAINT_TOPIC.search(topic) or OTHER_COMPLAINT_PROCESS.search(topic):
            return None

    answers = []
    if re.search(r"ไปวันไหน|ยื่นวันไหน|เวลาใด|เวลาไหน|กี่โมง|เวลาทำการ|เวลาให้บริการ|วันเสาร์|วันอาทิตย์|วันหยุด", question):
        answers.append("ตามคู่มือ สำนักงานรับเรื่องโดยตรงวันจันทร์ถึงวันศุกร์ เวลา 08.30–16.30 น. ค่ะ")
    if re.search(r"ค่าธรรมเนียม|ค่าใช้จ่าย|จ่ายเงินไหม|ต้องจ่ายไหม|เสียเงินไหม|ฟรีไหม", question):
        answers.append("การยื่นเรื่องร้องเรียนหรือร้องทุกข์ไม่มีค่าธรรมเนียมค่ะ")
    if re.search(r"(?:ต้อง|ใช้|เตรียม|แนบ)เอกสาร|เอกสารอะไร|เอกสารประกอบ|แนบอะไร|ใช้บัตร|สำเนาบัตร", question):
        answers.append(
            "กรณีกรอกแบบฟอร์มร้องเรียน ให้แนบสำเนาบัตรประจำตัวประชาชน "
            "ส่วนการร้องเรียนผ่านเว็บไซต์ คู่มือระบุว่าไม่มีเอกสารประกอบค่ะ"
        )
    if re.search(r"ตรวจสอบ|ระยะเวลา|กี่วัน|15วัน|๑๕วัน|เสร็จเมื่อไหร่|เสร็จเมื่อไร", question):
        answers.append(
            "คู่มือระบุให้ตรวจสอบข้อร้องเรียนภายใน 15 วัน โดยขึ้นอยู่กับเรื่องที่ร้องเรียน "
            "คู่มือไม่ได้กำหนดว่าเรื่องจะต้องแก้ไขเสร็จภายใน 15 วันค่ะ"
        )
    if not answers:
        return None
    return "\n\n".join(answers) + f"\n\n[คู่มือร้องเรียนและร้องทุกข์ หน้า 1]({COMPLAINT_GUIDE_URL})", COMPLAINT_GUIDE_URL


def lookup(question: str) -> tuple[str, str] | None:
    question = "".join(question.split())
    if any(term in question for term in ("เบอร์เทศบาล", "เบอร์โทรเทศบาล", "เบอร์โทรของเทศบาล", "เบอร์ติดต่อเทศบาล", "ที่อยู่เทศบาล", "ติดต่อเทศบาลเมืองศิลา")):
        return (
            "โทรสำนักงานเทศบาลเมืองศิลาได้ที่ 043-246505 หรือ 043-246506 ค่ะ\n\n"
            "สำนักงานอยู่ที่ 722 หมู่ 14 ตำบลศิลา อำเภอเมืองขอนแก่น จังหวัดขอนแก่น 40000",
            CONTACT_URL,
        )
    if any(term in question for term in ("ร้องเรียนที่ไหน", "ช่องทางร้องเรียน", "แจ้งเรื่องร้องเรียน", "ร้องเรียนอย่างไร")):
        return "ส่งเรื่องได้ที่ [ช่องทางร้องเรียนของเทศบาล](" + COMPLAINT_URL + ") ค่ะ", COMPLAINT_URL
    if "แบบฟอร์ม" in question and ("ที่ไหน" in question or "ดาวน์โหลด" in question):
        return "เลือกเอกสารได้จาก [หน้าแบบฟอร์มเทศบาล](" + FORMS_URL + ") ค่ะ", FORMS_URL
    if "ข่าวประชาสัมพันธ์" in question and ("ที่ไหน" in question or "ติดตาม" in question):
        return "ติดตามได้ที่ [หน้าข่าวประชาสัมพันธ์เทศบาล](" + NEWS_URL + ") ค่ะ", NEWS_URL
    if any(term in question for term in ("ขอดูคู่มือ", "คู่มือประชาชนอยู่ที่ไหน", "คู่มือสำหรับประชาชน")):
        return "ดู [คู่มือสำหรับประชาชน](" + GUIDES_URL + ") บนเว็บไซต์เทศบาลได้ค่ะ", GUIDES_URL
    return None
