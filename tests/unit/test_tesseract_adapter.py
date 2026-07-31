from workers.cascade.tesseract_adapter import parse_tsv


def test_parse_tesseract_tsv_to_common_text_lines():
    payload = (
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
        "5\t1\t1\t1\t1\t1\t10\t20\t30\t12\t95.5\tHELLO\n"
        "5\t1\t1\t1\t1\t2\t45\t20\t20\t12\t-1\t\n"
    )
    assert parse_tsv(payload) == [
        __import__("workers.page_detection.text_extraction", fromlist=["TextLine"]).TextLine(
            "HELLO", 10, 20, 40, 32, 0.955
        )
    ]
