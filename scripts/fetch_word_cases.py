import json
import urllib

from urllib.request import urlopen
from config import MUNICIPALITIES_FP, ALL_MUNIS_FP


""" Feed a file of czech words in nominative, call the API and get all word-cases for each of the words. """

# Linguistic research site with nice public api ==> # "https://lindat.mff.cuni.cz/services/morphodita/api-reference.php"
API_URL = "http://lindat.mff.cuni.cz/services/morphodita/api/generate"
INPUT_FP = MUNICIPALITIES_FP
OUTPUT_FP = ALL_MUNIS_FP
# INPUT_FP = DISTRICTS_FP
# OUTPUT_FP = ALL_DISTRICTS_FP


def parse_response_for_list(result: str) -> set[str]:
    """ Returns a flat list of all the results in random order. """
    forms = set()
    for line in result.strip().split('\n'):
        if not line.strip():
            continue
        tokens = line.strip().split('\t')
        forms.update(tokens[i] for i in range(0, len(tokens), 3))
    return forms


def parse_response_for_map(result) -> dict[str, str]:
    """ Returns a dict mapping each case to its nominative. """
    form_map = {}
    for line in result.strip().split('\n'):
        if not line.strip():
            continue
        tokens = line.strip().split('\t')
        for i in range(0, len(tokens), 3):
            form = tokens[i]
            lemma = tokens[i + 1].split('_')[0]  # strip the _;G suffix
            form_map[form] = lemma
    return form_map


def fetch_data(base_words: set):
    """ Expects a set of words. """
    try:
        boundary = "----boundary"
        body = (
            f"--{boundary}\n"
            f'Content-Disposition: form-data; name="data"; filename="input.txt"\r\n'
            f'Content-Type: text/plain\r\n\r\n'
            f"{'\n'.join(base_words)}\r\n"
            f"--{boundary}--\n"
        ).encode('utf-8')
        req = urllib.request.Request(API_URL, data=body)
        req.add_header("Content-Type", "multipart/form-data; boundary=%s" % boundary)
        response = urllib.request.urlopen(req)

        print(f"Response stats:: {response.status}")
        if response.status != 200:
            print(f"Failed getting soup, returning...")
            raise response.read()

        result = json.loads(response.read())["result"]
        return parse_response_for_map(result)

    except Exception:
        raise

def main():
    print("Starting the script")
    input_data = None
    with open(INPUT_FP, 'r', encoding='utf-8') as f:
        input_data = set(f.read().splitlines())

        # # Used for the stored "districts" (which are in format "District(Region)")
        # raw_input_data = f.read().splitlines()
        # input_data = set()
        # for word in raw_input_data:
        #       # Remove the region
        #     split_word = word.split('(')[0]
        #     input_data.add(split_word)

    print(f"Calling the api with {len(input_data)} words...")
    res: dict = fetch_data(input_data)
    with open(OUTPUT_FP, 'w', encoding='utf-8') as f:
        json.dump(res, f, ensure_ascii=False)

    print(f"Finished saving {len(res)} words out of the original {len(input_data)} files.")
    print("Exiting")
    return

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(e)
        exit()
