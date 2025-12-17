import ast
import json

from config import YEAR_LINKS2_FP


def main():
    with open(YEAR_LINKS2_FP, 'r') as f:
        raw = f.read()

    # Interpret the raw text as a Python dict
    data = ast.literal_eval(raw)

    with open(YEAR_LINKS2_FP, 'w') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()