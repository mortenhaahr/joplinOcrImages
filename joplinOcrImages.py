#!/usr/bin/env python3
import requests
import copy
import re
import sys
from PIL import Image
import io
import pytesseract
import json

API_TOKEN = '7302229ee77697943426f8b38bba4c154c562f330020c3e9bed4950580cb0ce0807ee23ffa0f71d07f1eee79833b0914b552c7cb71f649b686525fd5dedb49c9'
MIME = 'multipart/form-data'

def main():
    # Get parent folder:
    argv = sys.argv.copy() # Copy because we want to manipulate
    script_name = argv[0]
    argv.pop(0)
    tree_length = len(argv)
    if(tree_length < 0):
        print(f"Usage: {script_name} [parent-notebooks] <note-name>")
        exit(-1)
    
    tree = []
    for i in range(tree_length):
        tree.append(argv[i])

    parent_length = tree_length - 1
    parents_reversed = tree[:-1]
    parents_reversed.reverse()

    # Test connection
    params = {"token": API_TOKEN}
    try:
        response = requests.get(
            'http://localhost:41184/ping', params=params)
        response.raise_for_status()
    except requests.exceptions.HTTPError as err:
        print("Couldn't ping the server")
        raise SystemExit(err)
    
    # Search for notes:
    try:
        response = requests.get(
            f'http://localhost:41184/search?query="{tree[-1]}"', params=params)
        response.raise_for_status()
    except requests.exceptions.HTTPError as err:
        print("Couldn't ping the server")
        raise SystemExit(err)
    body = response.json()
    candidates = [{'id': x['id'], 'parent_id': x['parent_id']} for x in body['items']]
    candidates_copy = copy.deepcopy(candidates)
    candidate_index = 0
    # Search for correct notebook to isolate wrong candidates
    for candidate in candidates:
        search_id = candidate["parent_id"]
        parents_reversed_len = len(parents_reversed)
        for i, parent_title in enumerate(parents_reversed):
            try:
                response = requests.get(
                    f'http://localhost:41184/folders/{search_id}', params=params)
                response.raise_for_status()
            except requests.exceptions.HTTPError as err:
                print("Couldn't ping the server")
                raise SystemExit(err)
            body = response.json()
            if body['title'] != parent_title:
                candidates_copy.pop(candidate_index)
                candidate_index -= 1
                break
            # If we are not at the final parent, but the parent_id is empty.
            # Happens when the match is good, but we expected a parent.
            elif i != parents_reversed_len - 1 and not body['parent_id']:
                candidates_copy.pop(candidate_index)
                candidate_index -= 1
                break
            else:
                search_id = body['parent_id']
        candidate_index += 1

    candidates = candidates_copy
    if not len(candidates) == 1:
        print("Something went wrong with finding the correct note. Exiting")
        exit(-1)

    notebook_page_id = candidates[0]['id']

    # Get page body:
    try:
        response = requests.get(
            f'http://localhost:41184/notes/{notebook_page_id}?fields=id,body', params=params)
        response.raise_for_status()
    except requests.exceptions.HTTPError as err:
        print("Couldn't retrieve page body")
        raise SystemExit(err)
    body = response.json()
    page_body = body['body']

    # Regex stolen from https://regex101.com/r/u2DwY2/2/ , but modified for grp 2 to also match on "".
    md_file_re = r'!\[[^\]]*\]\((.*?)\s*("(?:.*)")?\s*\)'
    file_matches = re.findall(md_file_re, page_body)
    # Return all the files where there is no alternative text and that are native Joplin resources
    file_ids = [file_match[0] for file_match in file_matches if not file_match[1] and file_match[0].startswith(":/")]
    file_ids = [file[2:] for file in file_ids] # Remove ":/"
    image_ids = []

    # Check that the files are images and exist in the db. (Perhpas unnecessary)
    for file_id in file_ids:
        try:
            response = requests.get(
                f'http://localhost:41184/resources/{file_id}?fields=id,file_extension', params=params)
            response.raise_for_status()
        except requests.exceptions.HTTPError as err:
            print(f"Failed to retrieve for resource {file_id}. Continuing.")
        body = response.json()
        if not (body['file_extension'].lower() == 'png' or body['file_extension'].lower() == 'jpg'):
            print(f"Skipping {file_id} as it is not a .png or .jpg file.")
            continue        
        image_ids.append({'id': file_id, 'alt_text': ""})

    # Do OCR on the images
    for image_id in image_ids:
        try:
            response = requests.get(
                f"http://localhost:41184/resources/{image_id['id']}/file", params=params)
            response.raise_for_status()
        except requests.exceptions.HTTPError as err:
            print(f"Failed to retrieve for resource {file_id}. Continuing.")

        image = Image.open(io.BytesIO(response.content))
        #image.show()
        image_text = pytesseract.image_to_string(image)
        # Replace what is not allowed - in the most inefficient manner...
        image_text = image_text.replace("\n", " ")
        image_text_chars = []
        for char in image_text:
            if char.isalnum():
                image_text_chars.append(char)
            else:
                image_text_chars.append(" ") # Append a space seems to be the best for searching
        image_text = "".join(image_text_chars)
        image_id['alt_text'] = image_text

    # Make new page body
    new_page_body = page_body
    for image_id in image_ids:
        new_page_body = new_page_body.replace(image_id['id'], f'{image_id["id"]} "{image_id["alt_text"]}"')
    
    # Upload new page body
    try:
        response = requests.put(f'http://localhost:41184/notes/{notebook_page_id}', params=params, data=json.dumps({'body': new_page_body}))
        response.raise_for_status()
    except requests.exceptions.HTTPError as err:
        print(f"Failed edit notebook page. Exiting")
        raise SystemExit(err)


# ![image0.jpg](:/62108bdfcad8482a93518e307f2c8a78)<br><br>
# I am a note. Hej
# ![image1.jpg](:/8ea4f852ea344aeca8932e633c3df04e "")<br><br> Dav
# ![image2.jpg](:/ff3c7e8e22f94735b215f68239471c7d "Hello alt text")<br><br>
# ![image3.jpg](:/10f8e0a942e24e03ab47d5d75c69de38)<br><br>
# ![image4.jpg](:/f1f1655aebfb45f7bfc252d9035d693b)<br><br>
# ![image5.jpg](:/5c7f84d8638b4dbb827fa82cb9e83670)<br><br>
# ![image6.jpg](:/bcf649849e1445788292cf1bf24732bc)<br><br>
# ![image7.jpg](:/bab2cd1b54dd448fa26974a61c8b7dd7)<br><br>
# ![image8.jpg](:/04f78a5fd6354f9ead24be60a4198f5e)<br><br>
# ![image9.jpg](:/e1d0e185d254424c982c742ab0e5b060)<br><br>
# ![image10.jpg](:/18406ec932694993bfe313da172187c7)<br><br>



if __name__ == "__main__":
    main()
