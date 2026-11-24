"""Measure the local answer pipeline and PDF/OCR without contacting any provider."""

import argparse
import asyncio
import json
import os
import statistics
import unicodedata
from collections import Counter
from contextlib import nullcontext
from math import sqrt
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pymupdf
from fastapi import FastAPI

DOC = {
    "id": 12,
    "content": "ตัวอย่างสมมุติ: จุดบริการเปิดเวลา 08:45 น. วันจันทร์",
    "category": "เวลาเปิดทำการ",
    "original_name": "คู่มือทดสอบ.pdf",
    "page_number": 3,
}
CONTACT = "ติดต่อเทศบาลเมืองศิลาได้ทางไหนบ้าง"
RETRIEVAL_DOCS = {
    "building": "ขออนุญาตก่อสร้างอาคาร ใช้แบบคำขอก่อสร้างและสำเนาโฉนด",
    "tax": "ชำระภาษีที่ดินและสิ่งปลูกสร้าง ติดต่อกองคลัง",
    "complaint": "ร้องเรียนและร้องทุกข์ผ่านเว็บไซต์เทศบาล",
    "elderly": "ลงทะเบียนเบี้ยยังชีพผู้สูงอายุ ติดต่อกองสวัสดิการสังคม",
    "waste": "ติดต่อเจ้าหน้าที่เก็บขยะตามวันและรอบของชุมชน",
    "contact": "ติดต่อสำนักงานเทศบาล โทรศัพท์ 043-246505",
    "permit": "ขอใบอนุญาตประกอบกิจการค้า ติดต่อกองสาธารณสุข",
    "feedback": "สอบถามและแจ้งปัญหาบริการประชาชนผ่านช่องทางร้องเรียน",
}
RETRIEVAL_LABELS = (
    ("ขออนุญาตก่อสร้างอาคารใช้เอกสารอะไร", {"building"}),
    ("อยากชำระภาษีที่ดินต้องไปที่ไหน", {"tax"}),
    ("แจ้งเรื่องร้องเรียนผ่านช่องทางไหน", {"complaint", "feedback"}),
    ("สมัครเบี้ยยังชีพผู้สูงอายุที่ไหน", {"elderly"}),
    ("ติดต่อรถขนมูลฝอยอย่างไร", {"waste"}),
    ("เบอร์โทรเทศบาลคืออะไร", {"contact"}),
)


def checks(doc, response, wanted, excluded=(), *, message="จุดบริการสมมุติเปิดกี่โมง", status=200, recent=()):
    return doc, response, wanted, excluded, message, status, recent


def chat_cases(chat):
    missing = ("ยังไม่พบข้อมูลที่ยืนยัน",)
    cases = {
        "official-contact": checks((), (), ("043-246505", "sila-kk.go.th/contactus.php"), message=CONTACT),
        "grounded-answer": checks(
            [DOC], ['{"answer":"เปิดเวลา 08:45 น.","sources":[1]}'], ("08:45", "คู่มือทดสอบ.pdf (หน้า 3)"),
        ),
        "no-search-match": checks((), (), missing),
        "missing-citation": checks([DOC], ['{"answer":"เสียค่าธรรมเนียม 500 บาท","sources":[]}'], missing, ("500",)),
        "unknown-citation": checks([DOC], ['{"answer":"เสียค่าธรรมเนียม 500 บาท","sources":[98]}'], missing, ("500",)),
        "untrusted-output-url": checks(
            [DOC], ['{"answer":"เปิดเวลา 08:45 น. [เปิดเว็บ](https://example.invalid)","sources":[1]}'],
            ("08:45", "คู่มือทดสอบ.pdf"), ("example.invalid",),
        ),
        "follow-up": checks(
            [DOC], ["จุดบริการสมมุติเปิดกี่โมง", '{"answer":"08:45 น.","sources":[1]}'],
            ("08:45", "หน้า 3"), message="แล้วเปิดกี่โมง", recent=({"role": "user", "content": "ขอข้อมูลจุดบริการสมมุติ"},),
        ),
        "bad-model-json": checks([DOC], ["invalid model response"], missing),
        "provider-outage": checks(
            [DOC], [chat.AIUnavailable("synthetic outage")], ("ระบบตอบคำถามขัดข้อง",), status=503,
        ),
        "unsupported-fee-valid-id": checks(
            [DOC], ['{"answer":"ค่าธรรมเนียม 500 บาท","sources":[1]}'], missing, ("500",),
            message="จุดบริการสมมุติเก็บค่าธรรมเนียมเท่าไร",
        ),
    }
    # Gold labels describe evidence availability, independent of whether a
    # malformed model response is safely refused. Outages are excluded.
    truth = {
        "official-contact": True,
        "grounded-answer": True,
        "no-search-match": False,
        "missing-citation": True,
        "unknown-citation": True,
        "untrusted-output-url": True,
        "follow-up": True,
        "bad-model-json": True,
        "unsupported-fee-valid-id": False,
    }
    return cases, truth


def repair_cases():
    missing = ("ยังไม่พบข้อมูลที่ยืนยัน",)
    grounded = ("08:45", "คู่มือทดสอบ.pdf (หน้า 3)")
    corrected = '{"answer":"เปิดเวลา 08:45 น.","sources":[1]}'
    invalid_responses = {
        "malformed-json": "invalid model response",
        "missing-citation": '{"answer":"เปิดเวลา 08:45 น.","sources":[]}',
        "unknown-citation": '{"answer":"เปิดเวลา 08:45 น.","sources":[98]}',
    }
    cases = {}
    truth = {}
    for name, invalid in invalid_responses.items():
        cases[f"recoverable-{name}"] = checks([DOC], [invalid, corrected], grounded)
        cases[f"persistent-{name}"] = checks([DOC], [invalid, invalid], missing, ("08:45",))
        truth[f"recoverable-{name}"] = truth[f"persistent-{name}"] = True
    cases["no-evidence-fee"] = checks(
        [DOC], ['{"answer":"ค่าธรรมเนียม 500 บาท","sources":[1]}'], missing, ("500",),
        message="จุดบริการสมมุติเก็บค่าธรรมเนียมเท่าไร",
    )
    truth["no-evidence-fee"] = False
    return cases, truth


async def evaluate_chat(repeats, chat, cases, truth):
    app = FastAPI()
    app.state.limiter = chat.limiter
    app.include_router(chat.router)
    rows = []
    confusion = Counter()
    # Isolate repeated requests from the production rate limiter counter.
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://evaluation.local",
    ) as client:
        for name, (docs, replies, needed, excluded, message, status, recent) in cases.items():
            elapsed = []
            passed = 0
            call_counts = []
            for _ in range(repeats):
                rpc = Mock()
                rpc.execute.return_value = SimpleNamespace(data=[dict(row) for row in docs])
                # If a repair retry is attempted beyond the declared responses,
                # repeat the final fixture response as a persistent condition.
                responses = (*replies, replies[-1]) if replies else ()
                generator = AsyncMock(side_effect=responses)
                with (
                    patch.object(chat, "embed_text", AsyncMock(return_value=[0.5])) as embed,
                    patch.object(chat, "generate_answer", generator),
                    patch.object(chat.supabase, "rpc", return_value=rpc),
                    patch.object(chat, "_add_metadata"),
                    patch.object(chat, "record_usage"),
                ):
                    started = perf_counter()
                    response = await client.post(
                        "/chat", json={"message": message, "recent": recent, "no_save": True},
                    )
                    elapsed.append((perf_counter() - started) * 1000)
                    body = response.json()
                    answer = body.get("answer", body.get("error", ""))
                    if name in truth:
                        predicted = response.status_code == 200 and bool(answer) and answer != chat.NO_MATCH
                        confusion[(truth[name], predicted)] += 1
                    correct = (
                        response.status_code == status
                        and all(item in answer for item in needed)
                        and all(item not in answer for item in excluded)
                    )
                    if name == "official-contact":
                        correct = correct and not generator.called and not embed.called
                    if name == "follow-up":
                        correct = correct and embed.called and embed.call_args.args == ("จุดบริการสมมุติเปิดกี่โมง",)
                    passed += bool(correct)
                    call_counts.append(generator.await_count)
                    chat.limiter.reset()
            rows.append({
                "case": name, "passed": passed, "trials": repeats,
                "generation_calls_per_trial": call_counts,
                "median_ms": round(statistics.median(elapsed), 2),
            })
    return rows, classification_metrics(confusion)


async def evaluate_repair(repeats, chat):
    cases, truth = repair_cases()

    async def generate_once(prompt, _source_count):
        return await chat.generate_answer(
            prompt, instructions=chat.ANSWER_INSTRUCTIONS, response_schema=chat.ANSWER_SCHEMA,
        )

    repair_available = hasattr(chat, "_generate_with_sources")
    baseline = patch.object(chat, "_generate_with_sources", generate_once) if repair_available else nullcontext()
    with baseline:
        before, baseline_metrics = await evaluate_chat(repeats, chat, cases, truth)
    result = {"generation_once": {"cases": before, "answerability": baseline_metrics}}
    if repair_available:
        after, repair_metrics = await evaluate_chat(repeats, chat, cases, truth)
        result["bounded_repair"] = {"cases": after, "answerability": repair_metrics}
    return result


def classification_metrics(confusion):
    tp, tn = confusion[True, True], confusion[False, False]
    fp, fn = confusion[False, True], confusion[True, False]

    def ratio(numerator, denominator):
        return round(numerator / denominator, 4) if denominator else None

    return {
        "tp": tp, "tn": tn, "fp": fp, "fn": fn,
        "accuracy": ratio(tp + tn, tp + tn + fp + fn),
        "precision": ratio(tp, tp + fp),
        "recall": ratio(tp, tp + fn),
        "f1": ratio(2 * tp, 2 * tp + fp + fn),
    }


def trigram_counts(text):
    text = normalized(text).casefold()
    return Counter(text[position:position + 3] for position in range(len(text) - 2))


def similarity(left, right):
    overlap = sum(count * right[token] for token, count in left.items())
    norm = sqrt(sum(count**2 for count in left.values()) * sum(count**2 for count in right.values()))
    return overlap / norm if norm else 0.0


def evaluate_retrieval():
    indexed = {doc_id: trigram_counts(text) for doc_id, text in RETRIEVAL_DOCS.items()}
    cutoffs = (1, 3, 5)
    rows = []
    for question, relevant in RETRIEVAL_LABELS:
        query = trigram_counts(question)
        ranked = sorted(indexed, key=lambda doc_id: (-similarity(query, indexed[doc_id]), doc_id))
        row = {
            "question": question,
            "relevant": sorted(relevant),
            "ranking": ranked,
            "reciprocal_rank": next(1 / rank for rank, doc_id in enumerate(ranked, 1) if doc_id in relevant),
        }
        for k in cutoffs:
            row[f"recall_at_{k}"] = len(relevant.intersection(ranked[:k])) / len(relevant)
        rows.append(row)
    return {
        "method": "offline character trigram cosine",
        "labeled_queries": len(rows),
        "corpus_size": len(indexed),
        "mrr": round(statistics.mean(row["reciprocal_rank"] for row in rows), 4),
        **{f"recall_at_{k}": round(statistics.mean(row[f"recall_at_{k}"] for row in rows), 4) for k in cutoffs},
        "per_query": rows,
    }


def normalized(text):
    return "".join(unicodedata.normalize("NFC", text).split())


def error_rate(expected, actual):
    previous = list(range(len(actual) + 1))
    for row, expected_char in enumerate(expected, 1):
        current = [row]
        for column, actual_char in enumerate(actual, 1):
            current.append(min(
                previous[column] + 1, current[column - 1] + 1,
                previous[column - 1] + (actual_char != expected_char),
            ))
        previous = current
    return previous[-1] / len(expected)


def word_tokens(text, tokenize):
    return [token for token in tokenize(unicodedata.normalize("NFC", text)) if any(char.isalnum() for char in token)]


def pdf_fixture(font_path, *, raster_dpi=None, rotation=0):
    english = "Municipal document 2026"
    thai = "เทศบาลเมืองศิลา เปิดบริการเวลา 08:45 น."
    with pymupdf.open() as native, pymupdf.open() as fixture:
        native.new_page(width=450, height=260).insert_text((55, 100), english, fontsize=23)
        thai_page = native.new_page(width=450, height=260)
        css = f"@font-face {{font-family: QAThai; src: url('{font_path.name}')}} p {{font-family: QAThai; font-size: 23pt}}"
        spare, _ = thai_page.insert_htmlbox(
            pymupdf.Rect(35, 55, 415, 205), f"<p>{thai}</p>",
            css=css, archive=pymupdf.Archive(str(font_path.parent)),
        )
        if spare < 0:
            raise RuntimeError("Thai test sample did not fit")
        fixture.insert_pdf(native, from_page=0, to_page=0)
        if raster_dpi is None:
            fixture.insert_pdf(native, from_page=1, to_page=1)
        else:
            width, height = (260, 450) if rotation else (450, 260)
            scan = fixture.new_page(width=width, height=height)
            scan.insert_image(scan.rect, pixmap=thai_page.get_pixmap(dpi=raster_dpi), rotate=rotation)
        return fixture.tobytes(), [english, thai]


def evaluate_pdf(font, repeats, extract_pages, tokenize):
    output = []
    for label, dpi, rotation in (
        ("native PDF", None, 0), ("mixed 300 dpi", 300, 0),
        ("mixed 120 dpi", 120, 0), ("rotated Thai scan 300 dpi", 300, 90),
    ):
        fixture, expected = pdf_fixture(font, raster_dpi=dpi, rotation=rotation)
        elapsed, cer, wer = [], [], []
        ordered = 0
        for _ in range(repeats):
            started = perf_counter()
            pages = extract_pages(fixture)
            elapsed.append((perf_counter() - started) * 1000)
            ordered += int([page for page, _ in pages] == [1, 2])
            recognized = dict(pages)
            pairs = [(truth, recognized.get(number, "")) for number, truth in enumerate(expected, 1)]
            cer.append([error_rate(normalized(truth), normalized(actual)) for truth, actual in pairs])
            wer.append([error_rate(word_tokens(truth, tokenize), word_tokens(actual, tokenize)) for truth, actual in pairs])
        output.append({
            "fixture": label, "pages_per_trial": len(expected), "trials": repeats, "page_order_passed": ordered,
            "median_ms": round(statistics.median(elapsed), 2),
            "english_cer": round(statistics.mean(pair[0] for pair in cer), 4),
            "thai_cer": round(statistics.mean(pair[1] for pair in cer), 4),
            "english_wer": round(statistics.mean(pair[0] for pair in wer), 4),
            "thai_wer": round(statistics.mean(pair[1] for pair in wer), 4),
        })
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--thai-font", type=Path, help="Font file with Thai glyphs")
    parser.add_argument("--tessdata", type=Path, help="Directory containing tha/eng.traineddata")
    parser.add_argument("--chat-only", action="store_true", help="Skip PDF and OCR evaluation")
    parser.add_argument("--trials", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.trials <= 20:
        parser.error("--trials must be between 1 and 20")
    if not args.chat_only:
        if not args.thai_font or not args.thai_font.is_file():
            parser.error("--thai-font must point to a readable font")
        if not args.tessdata or not all((args.tessdata / f"{lang}.traineddata").is_file() for lang in ("tha", "eng")):
            parser.error("--tessdata must contain tha.traineddata and eng.traineddata")
        try:
            from pythainlp.tokenize import word_tokenize
        except ImportError:
            parser.error("Install evaluation dependencies from requirements-evaluation.txt")
        os.environ["TESSDATA_PREFIX"] = str(args.tessdata.resolve())

    # This evaluator replaces every hosted call with a fixture. Use only synthetic credentials.
    os.environ.update({
        "AI_PROVIDER": "gemini",
        "GEMINI_API_KEYS": "",
        "SUPABASE_URL": "https://example.invalid",
        "SUPABASE_SERVICE_ROLE_KEY": "evaluation-placeholder",
        "SESSION_SECRET": "evaluation-placeholder",
    })
    from routes import chat
    answers, answerability = asyncio.run(evaluate_chat(args.trials, chat, *chat_cases(chat)))
    output = {
        "chat_mocked": answers,
        "answerability_mocked": answerability,
        "retrieval_offline_baseline": evaluate_retrieval(),
        "repair_comparison_mocked": asyncio.run(evaluate_repair(args.trials, chat)),
    }
    if not args.chat_only:
        from pdf_service import extract_pages

        output["pdf_ocr_local"] = evaluate_pdf(
            args.thai_font, args.trials, extract_pages, lambda text: word_tokenize(text, engine="newmm", keep_whitespace=False),
        )
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
