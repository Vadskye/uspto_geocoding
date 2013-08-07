import sqlalchemy
import sqlalchemy.orm as orm
import sqlalchemy.ext.declarative as declarative
import sqlalchemy.sql.expression as expression
import geoalchemy_util
import itertools
import os
import datetime
import re

import alchemy
#The config file alchemy uses to store information
alchemy_config = alchemy.get_config()
#Used to query the database used for input and output
alchemy_session = alchemy.fetch_session()
#The path to the database which holds geolocation data
geo_data_dbpath = os.path.join(
    alchemy_config.get("location").get('path'),
    alchemy_config.get("location").get('database'))
geo_data_engine = sqlalchemy.create_engine('sqlite:///%s' % geo_data_dbpath)
geo_data_session_class = orm.sessionmaker(bind=geo_data_engine)
#Used to query the database that holds the data from google
#As well as a MaxMinds database containing every city in the world
geo_data_session = geo_data_session_class()
base = declarative.declarative_base()

#Stores an address disambiguated by the Google API
class RawGoogle(base):
    __tablename__ = 'raw_google'
    id = sqlalchemy.Column("rowid", sqlalchemy.Integer, primary_key=True)
    input_address = sqlalchemy.Column(sqlalchemy.String)
    city = sqlalchemy.Column(sqlalchemy.String)
    region = sqlalchemy.Column(sqlalchemy.String)
    country = sqlalchemy.Column(sqlalchemy.String)
    latitude = sqlalchemy.Column(sqlalchemy.REAL)
    longitude = sqlalchemy.Column(sqlalchemy.REAL)
    confidence = sqlalchemy.Column(sqlalchemy.REAL)

    def __init__(self, input_address, city, region, country, latitude, longitude, confidence):
        self.input_address = input_address
        self.city = city
        self.region = region
        self.country = country
        self.latitude = latitude
        self.longitude = longitude
        self.confidence = confidence

    def __repr__(self):
        return "<RawGoogle('%s','%s','%s','%s','%s')>" % (self.input_address, self.city, self.region, self.country, self.latitude, self.longitude, self.confidence)
        
#One of the cities in the world as stored in the MaxMinds database
class AllCities(base):
    __tablename__ = 'all_cities'
    id = sqlalchemy.Column("rowid", sqlalchemy.Integer, primary_key=True)
    city = sqlalchemy.Column(sqlalchemy.String)
    region = sqlalchemy.Column(sqlalchemy.String)
    country = sqlalchemy.Column(sqlalchemy.String)
    latitude = sqlalchemy.Column(sqlalchemy.REAL)
    longitude = sqlalchemy.Column(sqlalchemy.REAL)
    
    def __init__(self, city, region, country, latitude, longitude):
        self.city = city
        self.region = region
        self.country = country
        self.latitude = latitude
        self.longitude = longitude

#Perform geocoding on the data stored in alchemy.db provided by parsing XML
def main(limit=None, offset=0):
    t = datetime.datetime.now()
    print "geocoding started", t
    #Construct a list of all addresses which Google was capable of identifying
    #Making this now allows it to be referenced quickly later
    construct_valid_input_address_list(force_lowercase=True)
    #Get all of the raw locations in alchemy.db that were parsed from XML
    raw_parsed_locations = alchemy_session.query(alchemy.RawLocation).limit(limit).offset(offset)
    #If there are no locations, there is no point in continuing
    if raw_parsed_locations.count() == 0:
        return False
    print 'Constructed list of all parsed locations containing', raw_parsed_locations.count(), 'items'
    """
    grouped_loations will contain a list of dicts. Each dict will contain three values:
    raw_location = Location object containing the original location found in the XML
    matching_location = RawGoogle object containing the disambiguated location
    grouping_id = ID constructed from the city, region, and country of the matching_location
    """
    grouped_locations = []
    for instance in raw_parsed_locations:
        #Convert the location into a string that matches the Google format
        parsed_raw_location = geoalchemy_util.concatenate_location(instance.city, instance.state, instance.country)
        cleaned_location = geoalchemy_util.clean_raw_location(parsed_raw_location)
        #If the cleaned location has a match in the raw_google database,
        #we use that to classify it
        if input_address_exists(cleaned_location, force_lowercase=True):
            #Find the location from the raw_google database that matches this input
            matching_location = geo_data_session.query(RawGoogle).filter(
                                    sqlalchemy.func.lower(RawGoogle.input_address)==
                                    sqlalchemy.func.lower(cleaned_location)).first()
            grouping_id = u"{0}|{1}".format(matching_location.latitude, matching_location.longitude)
        else:
            """
            If there is no match in the raw_google database, we leave the location alone
            TODO: analyze the location's edit distance to make minor adjustments to it
            such that it can be matched. Particularly good if we can combine the
            all_cities database with the list of valid input_address values in the
            raw_google database.
            """
            print cleaned_location
            matching_location = RawGoogle(cleaned_location, '', '', '', '', '', -1)
            grouping_id = u"nolocationfound"
        grouped_locations.append({"raw_location": instance,
                                  "matching_location": matching_location,
                                  "grouping_id": grouping_id})
    print "grouped_locations created", datetime.datetime.now() - t
    t = datetime.datetime.now()
    #We now have a list of all locations in the file, along with their
    #matching locations and the id used to group them
    #Sort the list by the grouping_id
    keyfunc = lambda x: x['grouping_id']
    grouped_locations.sort(key=keyfunc)
    #Create an iterator that will access everything in the list with the same
    #grouping_id
    grouped_locations_enum = enumerate(itertools.groupby(grouped_locations, keyfunc))
    print "grouped_locations sorted", datetime.datetime.now() - t
    t = datetime.datetime.now()
    #Match the locations
    match_grouped_locations(grouped_locations_enum, t)
    
    alchemy_session.commit()

    print "Matches made!", datetime.datetime.now() - t
    unique_group_count = alchemy_session.query(expression.func.count(sqlalchemy.distinct(alchemy.Location.id))).all()
    print "%s groups formed from %s locations" % (unique_group_count, raw_parsed_locations.count())
    
def match_grouped_locations(grouped_locations_enum, t):
    for i, item in grouped_locations_enum:
        #grouping = a list of every grouped location with the same grouping_id
        # Note that a grouped_location is a dict, as described above
        #key = the grouping_id of all items in the list
        key, grouping = item
        #We need to get only the RawLocation objects back from the grouped_location dict
        #match_group is the list of RawLocation objects which we call match on
        match_group = []
        first_pass=True
        for grouped_location in grouping:
            print key
            match_group.append(grouped_location["raw_location"])
            if(first_pass):
                first_matching_location = grouped_location["matching_location"]
        """
        default is a dict containing the default values of the parameters
        (id, city, region, country, latitude, longtidue)
        for all locations that are part of the same group.
        Here we set the defaults to be the values for the first entry in the grouping
        In theory, all entries in the grouping should have the same lat/long.
        """
        default = {"id": key, "latitude":first_matching_location.latitude,
                   "longitude":first_matching_location.longitude}
        #No need to run match() if no matching location was found.
        if(key!="nolocationfound"):
            run_geo_match(key, default, match_group, i, t)
        
def run_geo_match(key, default, match_group, counter, runtime):
    most_freq = 0
    if len(match_group) > 1:
        # if key exists, look at the frequency
        # to determine the default summarization
        clean = alchemy_session.query(alchemy.Location).filter(alchemy.Location.id == key).first()
        if clean:
            param = clean.summarize
            param.pop("id")
            param.pop("latitude")
            param.pop("longitude")
            loc = alchemy_session.query(alchemy.RawLocation)\
                .filter(alchemy.RawLocation.city == param["city"])\
                .filter(alchemy.RawLocation.state == param["state"])\
                .filter(alchemy.RawLocation.country == param["country"])\
                .first()
            if loc:
                most_freq = len(loc.rawassignees) + len(loc.rawinventors)
                default.update(param)

        # took a look at the frequency of the items in the match_group
        for loc in match_group:
            freq = len(loc.rawassignees) + len(loc.rawinventors)
            if freq > most_freq:
                default.update(loc.summarize)
                most_freq = freq

    alchemy.match(match_group, alchemy_session, default, commit=False)
    if (counter + 1) % alchemy_config.get("location").get("commit_frequency") == 0:
        print " *", (counter + 1), datetime.datetime.now() - runtime
        alchemy_session.commit()
        
not_digit_pattern = re.compile(ur'[^\d]')
digit_pattern = re.compile(ur'\d')

#Take a list of features from output_address
#Now we have to identify what locations these features correspond to
#We focus on identifying city, state/region, and country
def identify_locations(feature_list):
    #Strip away excess whitespace for each location in the list
    feature_list = [feature.strip() for feature in feature_list]
    #Remove purely numerical locations
    feature_list = [feature for feature in feature_list if not_digit_pattern.search(feature)]
    return feature_list

def clean_raw_locations_from_file(inputfilename, outputfilename):
    inputfile = open(inputfilename, 'r')
    outputfile = open(outputfilename, 'w+')
    for line in inputfile:
        line = line.decode('utf8')
        line = geoalchemy_util.clean_raw_location(line)
        line = line.encode('utf8')
        outputfile.write(line)
        
def analyze_input_addresses(inputfilename):
    construct_valid_input_address_list()
    print datetime.datetime.now()
    inputfile = open(inputfilename, 'r')
    line_count=0
    good_count=0
    exists_in_all_cities_count=0
    #not_found_file = open('not_found.txt', 'w+')
    for line in inputfile:
        line = line.decode('utf8')
        input_address = geoalchemy_util.clean_raw_location(line)
        if input_address_exists(input_address):
            good_count+=1
        #else:
            #not_found_file.write('{0}\n'.format(input_address.encode('utf8')))
        line_count+=1
    print 'All lines compared!'
    print '% good:', good_count*1.0/line_count
    print '% in all_cities:', exists_in_all_cities_count*1.0/line_count
    print datetime.datetime.now()

valid_input_address_list = set()
def construct_valid_input_address_list(force_lowercase=False):
    temp = geo_data_session.query(RawGoogle.input_address).filter(RawGoogle.confidence>0)\
                                .filter((RawGoogle.city!='') | (RawGoogle.region!='')).all()
    for row in temp:
        input_address = row.input_address
        if force_lowercase:
            input_address = input_address.lower()
        valid_input_address_list.add(input_address)
    print 'List of all valid Google input_address values constructed with', len(valid_input_address_list), 'items'

def input_address_exists(input_address, force_lowercase=False):
    if valid_input_address_list:
        if force_lowercase:
            input_address = input_address.lower()
        return input_address in valid_input_address_list
    else:
        print 'Error: list of valid input addresses not constructed'
        return False
    
def find_difficult_locations(inputfilename, outputfilename):
    inputfile = open(inputfilename, 'r')
    outputfile = open(outputfilename, 'w+')
    t = datetime.datetime.now()
    all_japan_cities_query = geo_data_session.query(AllCities.city).filter(AllCities.country=='JP').group_by(AllCities.city).all()
    all_japan_cities = []
    for row in all_japan_cities_query:
        all_japan_cities.append(row.city)
    print 'list of all_japan_cities created', datetime.datetime.now()-t
    for line in inputfile:
        line = line.decode('utf8')
        line = geoalchemy_util.remove_eol_pattern.sub('', line)
        if line.endswith(', JP') or line.endswith(', JA'):
            city = line.split(',')[0].strip()
            most_similar_city = geoalchemy_util.get_closest_match_leven(city, all_japan_cities, 0.8)
            if most_similar_city!='':
                outputfile.write('{0}|{1}\n'.format(city.encode('utf8'), most_similar_city.encode('utf8')))
    print datetime.datetime.now()-t