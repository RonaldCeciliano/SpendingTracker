"""In-memory records packages with controlled, portable archive member names."""

from io import BytesIO
import re
import unicodedata
from zipfile import ZipFile, ZIP_STORED


ROOT = "ExpenseHQ Expense Records"


def receipt_export_stem(expense):
    """Keep Unicode letters/numbers; bound the vendor's UTF-8 filename length."""
    vendor = unicodedata.normalize("NFC", expense["vendor"])
    vendor = "".join(char if char.isalnum() else "-" for char in vendor)
    vendor = re.sub("-+", "-", vendor).strip("-")
    vendor = vendor.encode("utf-8")[:100].decode("utf-8", errors="ignore").rstrip("-") or "Vendor"
    dollars, cents = divmod(expense["amount"], 100)
    return f'{expense["date"]}_{vendor}_{dollars}.{cents:02d}'


def build_records_package(records, report, receipt_file):
    """Copy available receipts without modifying stored files or exposing identifiers.

    receipt_file is the application's existing validated storage resolver. Read
    each receipt before adding it so failed reads cannot leave partial members.
    """
    output = BytesIO()
    used_names = set()
    issues = []
    with ZipFile(output, "w", compression=ZIP_STORED) as archive:
        archive.writestr(f"{ROOT}/ExpenseHQ Expense Report.pdf", report.getvalue())
        for expense in records:
            if not expense["receipt_path"]:
                continue
            stem = receipt_export_stem(expense)
            try:
                path = receipt_file(expense["receipt_path"])
                if path is None or not path.is_file():
                    raise OSError("Receipt unavailable")
                contents = path.read_bytes()
            except OSError:
                issues.append(f"{stem}: Receipt could not be included.")
                continue
            name = stem + path.suffix
            suffix = 2
            # Case-insensitive uniqueness also protects extraction on Windows/macOS.
            while name.casefold() in used_names:
                name = f"{stem}_{suffix}{path.suffix}"
                suffix += 1
            used_names.add(name.casefold())
            archive.writestr(f"{ROOT}/Receipts/{name}", contents)
        if issues:
            archive.writestr(
                f"{ROOT}/Receipt Export Issues.txt",
                "Some receipts could not be included. The expenses remain in the PDF report.\n"
                "Expenses below are identified by date, vendor, and USD amount.\n\n"
                + "\n".join(issues) + "\n",
            )
    output.seek(0)
    return output
