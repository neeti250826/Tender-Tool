# Extracted from moh_scraper_notebook.ipynb. Review notebook shell commands before running locally.

# Notebook shell command cell:
# !pip -q install -r "requirements.txt"
# from google.colab import drive
# drive.mount('/content/drive')

# NOTE
# This notebook assumes it is run from the same folder as moh_scraper.py and requirements.txt.

# @title Config
DATE_FROM = '2026-03-01'  # @param {type:'string'}
DATE_TO = '2026-03-14'  # @param {type:'string'}
QUERY = 'digital'  # @param {type:'string'}
FILTER_MATCH = 'any'  # @param ['any','all','exact']
START = 0  # @param {type:'integer'}
OUTPUT_TARGET = './_local_outputs'  # @param {type:'string'}
PROJECT_NAME = 'MDT_2026'  # @param {type:'string'}
WEBSITE_ID = 'MY_MOH'  # @param {type:'string'}
SOURCE_LABEL = 'Malaysia MOH'  # @param {type:'string'}
REGION = 'EMEA'  # @param ['EMEA','LATAM']

# @title Advanced filters help
!python "moh_scraper.py" --list-advanced-filters

# Notebook shell command cell:
# !python "moh_scraper.py" \
#   --date-from "{DATE_FROM}" \
#   --date-to "{DATE_TO}" \
#   --query "{QUERY}" \
#   --filter-match "{FILTER_MATCH}" \
#   --start {START} \
#   --output-target "{OUTPUT_TARGET}" \
#   --project-name "{PROJECT_NAME}" \
#   --website-id "{WEBSITE_ID}" \
#   --source-label "{SOURCE_LABEL}" \
#   --region "{REGION}"

