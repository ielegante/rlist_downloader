import hashlib
import requests
import zipfile
from bson.binary import Binary
import re
from docx import Document
import os
import fitz  # PyMuPDF
from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
import json

uri = "mongodb+srv://<USERNAME>:<PASSWORD>@readinglist.9bnpotz.mongodb.net/?retryWrites=true&w=majority&appName=ReadingList"
citation_regex = r'(\[(\d{4})\]\s(\d+\s\w+\s\d+|\w+\s\d+))'

# Create a new client and connect to the server
client = MongoClient(uri, server_api=ServerApi('1'))

db = client.SG
collection = db.Cases

# Send a ping to confirm a successful connection
try:
    client.admin.command('ping')
    print("Pinged your deployment. You successfully connected to MongoDB!")
except Exception as e:
    print(e)

def load_json_from_gcp(url):
    response = requests.get(url)
    # Check if the request was successful
    if response.status_code == 200:
        json_data = response.json()
        return json_data
    else:
        print(f"Failed to retrieve file: HTTP {response.status_code}")
        return None

def extract_text_from_docx(docx_path):
    doc = Document(docx_path)
    full_text = []
    for para in doc.paragraphs:
        full_text.append(para.text)
    return '\n'.join(full_text)

def extract_text_from_pdf(pdf_path):
    doc = fitz.open(pdf_path)
    full_text = ''
    for page in doc:
        full_text += page.get_text()
    return full_text

def extract_legal_cases(text):
    # Simple regex pattern for case names, can be adjusted based on specific requirements
    pattern = r'\b([A-Za-z]+[\s]+v\.[\s]+[A-Za-z]+)\b'
    return re.findall(pattern, text)

# This will be stored on a GCP bucket
# A GCF will regularly ensure that this file is updated instead of the update being made
# every time the script is run
# with open('cases.json', 'r') as f:
#     cases_to_check = json.load(f)

# load cases_to_check from GCP
cases_to_check = load_json_from_gcp('https://storage.googleapis.com/ele_reading_list/cases.json')

# This file will also be stored on a GCP bucket
# and updated as and when an update is necessary
# this depends on when important cases are added - which is not very often
# with open('slr_citations.json', 'r') as f:
#     slr_citations = json.load(f)

# load slr_citations from GCP
slr_citations = load_json_from_gcp('https://storage.googleapis.com/ele_reading_list/slr_citations.json')

cases_to_check = [(entry['title'], entry['citation'], entry['url']) for entry in cases_to_check]
case_names = [entry[0] for entry in cases_to_check]
case_citations = [entry[1] for entry in cases_to_check]
case_urls = [entry[2] for entry in cases_to_check]

def file_hash(filepath):
    """Generate a SHA-256 hash for the given file."""
    sha256_hash = hashlib.sha256()
    with open(filepath, "rb") as f:
        # Read and update hash string value in blocks of 4K
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

def check_hash_on_mongo(collection, filehash):
    # return False
    """Check if the given hash exists in the database."""
    return collection.find_one({"hash": filehash})

def update_mongo(collection, filehash, cases_urls, reading_list_name, manifest):
    """Update the database with the given hash and cases."""
    post = { "hash": filehash, "cases_urls": cases_urls, "reading_list": reading_list_name, "manifest": manifest}
    return collection.insert_one(post).inserted_id

def download_from_mongo(collection, filehash):
    """Download the file from the database with the given hash."""
    return collection.find_one({"hash": filehash})

# Given a list of URLs, download the files, and zip them, and let the user download
def download_files(collection, filehash, urls, filename, manifest):
    # take an existing file name, and replace the .pdf or .docx with .zip
    # there might be other periods before the final period, so we need to split the string by periods, and then join all but the last one
    zipfilename = '.'.join(filename.split('.')[:-1]) + '.zip'

    """Download a list of files and zip them."""
    # Create a zip file to store the downloaded files
    with zipfile.ZipFile(zipfilename, 'w') as zipf:
        # Download each file and add to the zip file
        for url in urls:
            # Get the file name from the URL
            filename = url.split('/')[-1]
            # check whether filename is already in zipfile
            if filename in zipf.namelist():
                pass
            else:
                # Download the file
                response = requests.get(url+'/pdf')
                # Add the file to the zip file
                zipf.writestr(filename, response.content)
        # write the manifest to the zip file
        zipf.writestr('manifest.txt', manifest)
        update_mongo_with_zip(collection, filehash, zipfilename)

def update_mongo_with_zip(collection, filehash, zipfilename):
    # update existing document with the zip file that has been converted into a binary
    collection.update_one({"hash": filehash}, {"$set": {"zipfile": Binary(open(zipfilename, 'rb').read())}})
    return

def find_following_citation(text, case_name):
    # Escape special characters in case_name to use it in a regular expression
    case_name_escaped = re.escape(case_name)
    
    # Pattern to match the citation followed by the case name
    # Assuming a space, comma, or newline might be between them
    pattern = case_name_escaped + r'\s(\[(\d{4})\]\s(\d+\s\w+\s\d+|\w+\s\d+))'
    
    # Search for the pattern in the text
    match = re.search(pattern, text)
    
    if match:
        # constructing full citation strings from match tuples
        citation = match.group(1)
        year = match.group(2)
        # citations = [ '{} {}'.format(match[0], match[1]) for match in matches ]
        return citation, year
    else:
        return False, False

def process_reading_list(file):
    results = []
    slr_errors = []
    other_errors = []

    filehash = file_hash(file)
    # print(filehash)
    test_hash = check_hash_on_mongo(collection, filehash)
    print(test_hash)
    # check if hash in cache
    if test_hash:
        print('Reading list has been cached, utilising cache.')
        zipfile = test_hash['zipfile']
        zipfilename = ''.join(test_hash['reading_list'].split('.')[:-1]) + '.zip'

        # Write the binary data back to a ZIP file
        with open(zipfilename, 'wb') as file:
            file.write(zipfile)
        # Download zip file here

    else:
        # otherwise, compare against all case names
        print('Reading list has not been cached before, processing now.')
        if '.pdf' in file:
            text = extract_text_from_pdf(file)
            # print(text)
        elif '.docx' in file:
            text = extract_text_from_docx(file)
        # Remove all line breaks in text
        text = text.replace('\n', '')
        # print(text)
        
        # find all citations in text and store in list
        citations_in_text = re.findall(citation_regex, text)
        citations_in_text = [ i[0] for i in citations_in_text ]
        # print(citations_in_text)
            
        # then we compare against case names in the database
        for n, citation in enumerate(citations_in_text):
            # print(citation)

            # first we check whether it is an SLR citation
            if 'slr' in citation.lower():
                try:
                    # then we check whether we have it already
                    neutral_citation = slr_citations[citation]
                except:
                    try:
                        neutral_citation = slr_citations[citation.replace('SLR', 'SLR(R)')]
                    except:
                        # if we don't, we log it, if certain clarity conditions are met
                        print('SLR citation not found in database')
                        slr_errors.append(citation)
                        neutral_citation = 'Not available'
            else:
                # then we check whether it is a neutral citation
                if citation in case_citations:
                    print('Neutral citation found in database')
                    neutral_citation = citation
                else:
                    # if not both, we ignore
                    print('Citation not found in database', citation)
                    other_errors.append(citation)
                    neutral_citation = 'Not available'
            results.append((citation, neutral_citation))

        # if we have all the citations, we update the mongo database
        # we get the urls for each neutral citation
        cases_urls = [ case_urls[case_citations.index(citation[1])] for citation in results if citation[1] in case_citations ]
        # create string file for saving as txt, the manifest contains a list of all citations and their corresponding neutral citations
        # that can be downloaded from our database
        manifest = '\n'.join([ '{} - {}'.format(citation, neutral_citation) for citation, neutral_citation in results ])
        update_mongo(collection, filehash, cases_urls, file, manifest)
        # print(cases_urls)
        download_files(collection, filehash, cases_urls, file, manifest)
