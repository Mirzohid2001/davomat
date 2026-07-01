#!/usr/bin/env python3
"""Fill empty Russian translations in locale/ru/LC_MESSAGES/django.po (app strings only)."""
from pathlib import Path

PO_PATH = Path(__file__).resolve().parent.parent / "locale/ru/LC_MESSAGES/django.po"

# Extend RU dict as needed when adding new {% trans %} strings.
RU = {
    "Masalan: avans, qisman to'lov": "Например: аванс, частичная выплата",
    "Ism yoki lavozim bo'yicha qidirish...": "Поиск по имени или должности...",
    "Faol": "Активна",
    "Izoh/sabab kiritish majburiy!": "Примечание/причина обязательны!",
    "Sana formatida xatolik!": "Ошибка формата даты!",
}


def po_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def main():
    lines = PO_PATH.read_text(encoding="utf-8").splitlines(keepends=True)
    filled = 0
    still = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("msgid "):
            if line == 'msgid ""\n':
                msgid_parts = []
                j = i + 1
                while j < len(lines) and lines[j].startswith('"'):
                    msgid_parts.append(lines[j].strip().strip('"'))
                    j += 1
                msgid = "".join(p.replace("\\n", "\n") for p in msgid_parts)
                msgstr_idx = j
            else:
                msgid = line[7:-2].replace('\\"', '"').replace("\\\\", "\\")
                msgstr_idx = i + 1
            if msgstr_idx < len(lines) and lines[msgstr_idx] == 'msgstr ""\n' and msgid in RU:
                lines[msgstr_idx] = f'msgstr "{po_escape(RU[msgid])}"\n'
                filled += 1
            elif msgstr_idx < len(lines) and lines[msgstr_idx] == 'msgstr ""\n' and msgid:
                still.append(msgid[:80])
        i += 1
    PO_PATH.write_text("".join(lines), encoding="utf-8")
    print(f"Filled {filled} translations")
    if still:
        app_still = [s for s in still if not s.startswith("Enter ") and "django" not in s.lower()][:20]
        if app_still:
            print(f"App strings still empty ({len(app_still)} shown):")
            for s in app_still:
                print(f"  {s!r}")


if __name__ == "__main__":
    main()
