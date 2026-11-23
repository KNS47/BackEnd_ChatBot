"""Direct links for municipal services with verified official pages."""

CONTACT_URL = "https://www.sila-kk.go.th/contactus.php?menuid=13"
COMPLAINT_URL = "https://www.sila-kk.go.th/link.php?menuid=11"
GUIDES_URL = "https://www.sila-kk.go.th/pagelist.php?menuid=4"
FORMS_URL = "https://www.sila-kk.go.th/pagelist.php?menuid=47"
NEWS_URL = "https://www.sila-kk.go.th/newslist.php?menuid=84"


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
