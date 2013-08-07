import re
from bs4 import BeautifulSoup
import unicodedata
import Levenshtein as leven

#Return a ", " separated string of the location
def concatenate_location(city, state, country):
    location_list = []
    if(city!=''):
        location_list.append(city)
    if(state!=''):
        location_list.append(state)
    if(country!=''):
        location_list.append(country)
    location = ", ".join(location_list)
    return location

remove_eol_pattern = re.compile(ur'[\r\n]+')

#Many accent references are difficult to idenity programmatically.
#These are handled by manually replacing each entry.
#The replacements are stored in lib/manual_replacement_library.txt
#In the format: original_pattern|replacement
def generate_manual_patterns_and_replacements():
    manual_replacement_file = open("lib/manual_replacement_library.txt", 'r')
    manual_mapping_0 = []
    manual_mapping_1 = []
    replacement_count=0
    for line in manual_replacement_file:
        #allow # to be a comment
        if(line[0]=='#' or line=='\n'):
            continue
        line_without_newline = remove_eol_pattern.sub('',line)
        line_split = line_without_newline.split("|")
        #An individual re can only hold 100 entities. So split if necessary.
        if(replacement_count<99):
            manual_mapping_0.append((line_split[0],line_split[1].decode('utf-8')))
        else:
            manual_mapping_1.append((line_split[0],line_split[1].decode('utf-8')))
        replacement_count+=1
        
    #multisub, but only done once for speed
    manual_pattern_0 = '|'.join('(%s)' % re.escape(p) for p, s in manual_mapping_0)
    substs_0 = [s for p, s in manual_mapping_0]
    manual_replacements_0 = lambda m: substs_0[m.lastindex - 1]
    manual_pattern_compiled_0 = re.compile(manual_pattern_0, re.UNICODE)
    
    manual_pattern_1 = '|'.join('(%s)' % re.escape(p) for p, s in manual_mapping_1)
    substs_1 = [s for p, s in manual_mapping_1]
    manual_replacement_1 = lambda n: substs_1[n.lastindex - 1]
    manual_pattern_compiled_1 = re.compile(manual_pattern_1, re.UNICODE)
    
    return {'patterns':(manual_pattern_compiled_0, manual_pattern_compiled_1),
            'replacements':(manual_replacements_0, manual_replacement_1)}
    
def get_chars_in_parentheses(text):
    text = text.group(0)
    #match text surrounded by parentheses
    pattern = re.compile(ur'(?<=\().*?(?=\))', re.UNICODE)
    match = pattern.search(text)
    try:
        match = match.group(0)
    except:
        #Happens if the match is empty
        match = ''
    #Return an empty string instead of a single space because the single space means an empty string is more appropriate
    if not (match==' '):
        return match
    return ''

#We don't have manual replacements for every accent yet
#These patterns perform quick fixes which let us parse the data

def generate_quickfix_patterns():
    curly_pattern = re.compile(ur'\{.*?\}',re.UNICODE)
    quickfix_slashes = re.compile(ur'/[a-zA-Z]/',re.UNICODE)
    return {'curly':curly_pattern, 'slashes':quickfix_slashes}

manual_dict = generate_manual_patterns_and_replacements()
manual_patterns = manual_dict['patterns']
manual_replacements = manual_dict['replacements']
quickfix_patterns = generate_quickfix_patterns()
postal_pattern = re.compile(ur'(- )?[A-Z\-#\(]*\d+[\)A-Z]*', re.UNICODE)
foreign_postal_pattern = re.compile(ur'[A-Z\d]{3,4}[ ]?[A-Z\d]{3}', re.UNICODE)

separator_pattern = re.compile(ur'\|', re.UNICODE)

#Remove unnecessary symbols|whitespace in excess of one space|
#start of line symbols
unnecessary_symbols_pattern = re.compile(ur'[#\(?<!.\)]')
excess_whitespace_pattern = re.compile(ur'(?<= )( )+')
start_of_line_removal_pattern = re.compile(ur'^(late of|LATE OF)?[\-,/:;_& ]*', re.MULTILINE)
#A single letter followed by non-letters is unlikely to be useful information
#More likely, it is what remains of other removals, such as streets and addresses
start_of_line_letter_removal_pattern = re.compile(ur'^( )*[A-Za-z][\-, ]+', re.MULTILINE)
extra_commas_pattern = re.compile(ur'(( )*,( )*)+')

england_pattern = re.compile(ur', EN')
germany_pattern = re.compile(ur', DT')
japan_pattern = re.compile(ur', JA')
russia_pattern = re.compile(ur', SU')

#Input: a raw location from the parse of the patent data
def clean_raw_location(text):
    text = remove_eol_pattern.sub('', text)
    text = separator_pattern.sub(', ', text)
    #Perform all of the manual replacements
    i=0
    while i<len(manual_patterns):
        text = manual_patterns[i].sub(manual_replacements[i], text)
        i+=1
    #Perform all the quickfix replacements
    text = quickfix_patterns['curly'].sub(get_chars_in_parentheses, text)
    
    #Turn accents into unicode
    soup = BeautifulSoup(text)
    text = unicode(soup.get_text())
    text =  unicodedata.normalize('NFC', text)
    
    text = foreign_postal_pattern.sub('', text)
    text = postal_pattern.sub('', text)
    
    text = unnecessary_symbols_pattern.sub('', text)
    text = excess_whitespace_pattern.sub('', text)
    text = start_of_line_removal_pattern.sub('', text)
    text = start_of_line_letter_removal_pattern.sub('', text)
    text = extra_commas_pattern.sub(', ', text)
    #around commas
    text = england_pattern.sub(', GB', text)
    text = germany_pattern.sub(', DE', text)
    text = japan_pattern.sub(', JP', text)
    text = russia_pattern.sub(', RU', text)
    return text

def get_closest_match_leven(text, comparison_list, minimum_match_value):
    closest_match = ''
    closest_match_value=0
    for comparison_text in comparison_list:
        temp_match_value = leven.jaro(text, comparison_text)
        if temp_match_value>closest_match_value:
            closest_match = comparison_text
            closest_match_value = temp_match_value
    if closest_match_value>minimum_match_value:
        return closest_match
    else:
        return '' 