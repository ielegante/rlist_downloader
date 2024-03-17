# rlist_downloader
This script is the Python implementation of a program that processes law degree reading lists.

Here is what it does:
1. Extracts all citations from the reading list.
2. Identifies all SLR and SLR(R) citations.
3. Identifies whether there is an equivalent neutral citation.
4. If not, it logs these citations for subsequent analysis.
5. For non-Singapore/non-modern citations (after 2000), it ignores them.
6. For all citations with a neutral citation, we download the .pdfs, and collect them in a zip file for the user to download.
7. At the same time, it checks the MongoDB cache for whether the reading list has been processed before. The cache entry will also contain the zip file if the reading list has been processed before. This cuts down on processing and downloading time. By way of example, downloading the judgments for 5 reading lists required almost 25 minutes.

A few notes about the methodology. 
The SLR citations are generated from: i) top 200 most referenced citations in judgments; and ii) processing sample reading lists. Interestingly, SLR citations are not used nearly as much in judgments as in the reading lists - the difference in amount of usage is significant.
