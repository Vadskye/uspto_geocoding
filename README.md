uspto_geocoding
===============
This code is used to geocode locations associated with patent data from the United States Patent and Trademark office. It is designed to be run as part of a series of operations that turn raw XML into a useful database.

The main geocoding function requires two databases. The first is created by parsing the raw XML, and contains city, state, and country data for each patent. The second is created by processing a list of every raw location present in the patent data and and geocoding it. We accomplish this through collaboration with Google.