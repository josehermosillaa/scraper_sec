import argparse
import csv
import os
import sys
import time
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_INPUT = os.path.join(ROOT, "input.csv")
DEFAULT_OUTPUT = os.path.join(HERE, "input_agrupado.csv")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Agrupa CSV de DOB NOW por BIN, deduplica Job Filings, genera input_agrupado.csv"
    )
    parser.add_argument("--input", default=DEFAULT_INPUT, help=f"CSV de entrada (default: {DEFAULT_INPUT})")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help=f"CSV de salida (default: {DEFAULT_OUTPUT})")
    parser.add_argument("--log", default=None, metavar="FILE", help="Guardar conflictos en archivo (default: solo stdout)")
    return parser.parse_args()


def main():
    args = parse_args()

    if not os.path.exists(args.input):
        print(f"[!] No existe {args.input}")
        sys.exit(1)

    with open(args.input, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print(f"[*] Leidas {len(rows)} filas de {args.input}")

    bin_groups = defaultdict(list)
    for row in rows:
        bin_num = row.get("Bin", "").strip()
        if bin_num:
            bin_groups[bin_num].append(row)

    output_rows = []
    stats = {"bins": 0, "combos": 0, "dup_removed": 0, "conflicts": 0}
    conflicts_log = []

    for bin_num, group in sorted(bin_groups.items()):
        jfs = []
        seen = set()
        for row in group:
            jf = row.get("Job Filing Number", "").strip()
            if not jf:
                continue
            if jf in seen:
                stats["dup_removed"] += 1
                msg = f"BIN {bin_num}: Job Filing duplicado '{jf}' eliminado"
                print(f"[WARN] {msg}")
                conflicts_log.append(f"[DUP] {msg}")
                continue
            seen.add(jf)
            jfs.append(jf)

        first = group[0]
        for col in ["House No", "Street Name", "Borough", "Block", "LOT"]:
            vals = {row.get(col, "").strip() for row in group}
            if len(vals) > 1:
                stats["conflicts"] += 1
                chosen = first.get(col, "").strip()
                msg = f"BIN {bin_num}: '{col}' conflicto {vals}, usando '{chosen}'"
                print(f"[WARN] {msg}")
                conflicts_log.append(f"[COL] {msg}")

        output_rows.append({
            "Bin": bin_num,
            "House No": first.get("House No", "").strip(),
            "Street Name": first.get("Street Name", "").strip(),
            "Borough": first.get("Borough", "").strip(),
            "Job Filing Number": "|".join(jfs),
            "Block": first.get("Block", "").strip(),
            "LOT": first.get("LOT", "").strip(),
        })
        stats["bins"] += 1
        stats["combos"] += len(jfs)

    fieldnames = ["Bin", "House No", "Street Name", "Borough", "Job Filing Number", "Block", "LOT"]
    with open(args.output, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(output_rows)

    print()
    print(f"BINs unicos:          {stats['bins']}")
    print(f"Combinaciones:         {stats['combos']}")
    print(f"Duplicados eliminados: {stats['dup_removed']}")
    print(f"Conflictos columnas:   {stats['conflicts']}")
    print(f"Output:                {args.output}")

    if args.log and conflicts_log:
        with open(args.log, "w", encoding="utf-8") as lf:
            lf.write(f"Conflictos de formato.py — {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            lf.write(f"Input: {args.input}\n")
            lf.write(f"BINs unicos: {stats['bins']}  Combinaciones: {stats['combos']}\n")
            lf.write(f"Duplicados: {stats['dup_removed']}  Conflictos columna: {stats['conflicts']}\n")
            lf.write(f"{'=' * 60}\n\n")
            for entry in conflicts_log:
                lf.write(entry + "\n")
        print(f"Log conflictos:        {args.log}")


if __name__ == "__main__":
    main()
