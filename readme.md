# karma

Data analysis & visualization for your Facebook Messenger activity!

## Setup

Setup the Python environment with:

```bash
pip install requirements.txt
```

or, if using `conda`, with:

```bash
conda env create --file=environment.yaml
conda activate ig-liker
```

Scripts can then be run from the command line as follows:

```bash
python scrape.py
```

## Command-line options

Option|Usage
-|-
`--username`|Messenger login. If not set, will be prompted.
`--password`|Messenger password. If not set, will be prompted.

The following flags should not be given a value:

Flag|Usage
-|-
`--headless`|If set, the `chromedriver` will be run in headless mode. This may cause additional errors, but will not launch a GUI.
