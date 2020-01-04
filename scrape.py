import sys
import getopt
import getpass
import requests
import zipfile
import traceback
import io
import time
from selenium import webdriver
import selenium
import pathlib
from dateutil import parser
import json
import datetime
import uuid

# use the correct chromedriver for your chrome version!
CHROMEDRIVER_URL = "https://chromedriver.storage.googleapis.com/79.0.3945.36/chromedriver_win32.zip"


def get_cmd_line_opts(argv):
    # parse command line arguments
    try:
        opts, args = getopt.getopt(
            argv, "", ["username=", "password=", "headless"])
        opts = {opt[0]: opt[1] for opt in opts}
    except:
        print("Error parsing command-line arguments. Continuing...")
        opts = {}

    return opts


def get_username_password(opts):
    username = opts["--username"] if "--username" in opts.keys() else \
        input("Messenger username: ")
    password = opts["--password"] if "--password" in opts.keys() else \
        getpass.getpass("Messenger password: ")

    return username, password


def download_chromedriver(CACHE_DIR):
    try:
        request = requests.get(CHROMEDRIVER_URL)
        archive = zipfile.ZipFile(io.BytesIO(request.content))

        # extract first file from the archive
        file = archive.namelist()[0]
        chromedriver_file = archive.extract(file, CACHE_DIR)
        archive.close()
        print("Downloaded and extracted chromedriver to", chromedriver_file + ".")
    except:
        traceback.print_exc()
        chromedriver_file = CACHE_DIR + "chromedriver.exe"
        print("Exception while extracting chromedriver. Using default location of",
              chromedriver_file + ".")

    return chromedriver_file


def launch_chromedriver(USER_DATA_DIR, opts, chromedriver_file):
    try:
        chrome_options = selenium.webdriver.chrome.options.Options()
        chrome_options.add_argument("--user-data-dir=" + USER_DATA_DIR)
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--window-size=800,600")
        # chrome_options.add_argument("--start-maximized")
        chrome_options.add_argument("--disable-notifications")
        chrome_options.add_argument("--mute-audio")
        chrome_options.add_argument("--log-level=3")
        chrome_options.add_argument("--silent")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--allow-insecure-localhost")
        chrome_options.add_argument("--disable-extensions")
        if "--headless" in opts.keys():
            chrome_options.add_argument("--headless")

            # temp fix! must be set to some unused port
            chrome_options.add_argument("--remote-debugging-port=9222")
        driver = selenium.webdriver.Chrome(
            chromedriver_file, options=chrome_options)
        driver.implicitly_wait(0)
        print("Launched driver.")

        return driver
    except:
        traceback.print_exc()
        print("Failed to launch driver. Exiting...")

        return None


def login(driver, username, password):
    # try to login
    try:
        driver.get("https://www.messenger.com/")

        # clear email field if populated already!
        for a in range(100):
            try:
                driver.find_element_by_name("email").send_keys(
                    selenium.webdriver.common.keys.Keys.BACKSPACE)
            except:
                break
        driver.find_element_by_name("email").send_keys(username)
        driver.find_element_by_name("pass").send_keys(password)
        time.sleep(1)
        driver.find_element_by_xpath("//button[@type=\"submit\"]").click()
        time.sleep(3)
        print("Logged in.")
    except:
        print("Did not log in. Proceeding...")


def wait_for_loading(driver):
    aria_busy = driver.find_elements_by_css_selector(
        "i[aria-busy]")
    while len(aria_busy) > 0:
        time.sleep(0.1)
        aria_busy = driver.find_elements_by_css_selector(
            "i[aria-busy]")


def scroll_to_conversation_top(driver):
    driver.execute_script("arguments[0].parentNode.parentNode.parentNode.scrollTop = 0;",
                          driver.find_element_by_css_selector("div[aria-label='Messages']"))


def remove_webelement(driver, webelement):
    driver.execute_script("arguments[0].remove();", webelement)


def parse_div_with_tooltip_message(SCREENSHOT_DIR, driver, div_with_tooltip):
    message_by_self = div_with_tooltip.get_attribute(
        "data-tooltip-position") == "right"
    message_time = div_with_tooltip.get_attribute(
        "data-tooltip-content")

    # if the tooltip isn't a time, then this isn't a message!
    try:
        message_datetime = parser.parse(message_time)

        # mistakingly parses times in the future! so push back by a week if so
        if datetime.datetime.now() < message_datetime:
            message_datetime -= datetime.timedelta(days=7)
    except:
        # skip this div
        return None

    # try to parse type of message
    try:
        aria_divs = div_with_tooltip.find_elements_by_css_selector(
            "div[aria-label]")
        if len(aria_divs) < 1:
            # other
            # probably file, image, block of images, or forwarded message
            message_type = "other"
            message_content = ""
        else:
            # text or sticker
            message_div = aria_divs[0]
            message_content = message_div.get_attribute("aria-label")

            # check that this isn't a reaction button! if it is, skip
            message_div_role = message_div.get_attribute("role")
            if message_div_role == "button":
                return None

            # if has data-testid attribute, then it is a sticker
            if driver.execute_script("return arguments[0].hasAttribute('data-testid');", message_div):
                message_type = "sticker"
            else:
                message_type = "text"
    except:
        driver.save_screenshot(
            SCREENSHOT_DIR + "other-" + uuid.uuid4().hex + ".png")
        print("Could not parse message type! Screenshotted.")
        message_type = "other"
        message_content = ""

    # create message_info
    message_info = {
        "sender": "me" if message_by_self else "them",
        "datetime": message_datetime,
        "type": message_type,
        "content": message_content,
    }

    # try to print it!
    try:
        # may fail to print emojis or print junk for emojis
        print("[" + message_info["sender"] + "\t" +
              message_info["type"] + "\t]", message_info["content"])
    except:
        # might give OSError
        traceback.print_exc()

    return message_info


def save_conversations_json(CONVERSATIONS_FILE, conversations):
    with open(CONVERSATIONS_FILE, "w") as file:
        json.dump(conversations, file, indent=2, default=str)
    print("Saved conversations JSON.")


def select_next_conversation_or_quit(driver, conversations):
    conversation_nodes = driver.find_elements_by_css_selector(
        "ul[aria-label='Conversation List']>li>div>a[role='link']")
    if len(conversation_nodes) < 1:
        print("No more conversations. Terminating...")
        return None, None

    # get url identifying the first visible conversation
    # conversation is visible if it isn't parsed already
    for conversation_node in conversation_nodes:
        conversation_url = conversation_node.get_attribute("data-href")
        if conversation_url not in conversations.keys():
            break

    return conversation_node, conversation_url


def get_conversation_name(conversation_node):
    return conversation_node.find_element_by_css_selector("div[data-tooltip-content]").get_attribute(
        "data-tooltip-content")


def get_next_message_group(driver):
    # scroll to the top to prompt loading if last few message groups
    message_divs = driver.find_elements_by_css_selector("div#js_1>div")
    if len(message_divs) < 5:
        scroll_to_conversation_top(driver)
    wait_for_loading(driver)

    # this conversation is done only when no more top level divs
    message_groups = driver.find_elements_by_css_selector("div#js_1>*")
    if len(message_groups) < 1:
        return None

    # parse this message_group before deleting it
    return message_groups[-1]


def get_webelement_tag_name(driver, webelement):
    return driver.execute_script("return arguments[0].tagName;", webelement).lower()


def try_delete_message_group(driver, message_group):
    # delete this message_group
    try:
        # if last div, scroll to the top, wait for load, then wait 3 secs
        message_divs = driver.find_elements_by_css_selector("div#js_1>div")
        if len(message_divs) == 1:
            print("Last message div; being careful with deletion...")
            scroll_to_conversation_top(driver)
            wait_for_loading(driver)
            time.sleep(3)
        remove_webelement(driver, message_group)
        # print("Deleted message group.")
    except:
        # might be stale element; just retry
        pass


def scrape_conversation(SCREENSHOT_DIR, this_conversation, driver):
    # begin parsing messages
    while True:
        message_group = get_next_message_group(driver)
        if message_group is None:
            break

        # if is not div element, remove it and skip it!
        if get_webelement_tag_name(driver, message_group) != "div":
            remove_webelement(driver, message_group)
            continue

        # parse the messages
        divs_with_tooltips = message_group.find_elements_by_css_selector(
            "div[data-tooltip-content]")
        for div_with_tooltip in divs_with_tooltips:
            message_info = parse_div_with_tooltip_message(SCREENSHOT_DIR,
                                                          driver, div_with_tooltip)
            if message_info is None:
                continue
            this_conversation["messages"].append(message_info)

        try_delete_message_group(driver, message_group)


def run_scraper(SCREENSHOT_DIR, CONVERSATIONS_FILE, username, password, driver, conversations):
    login(driver, username, password)

    # go through each conversation in order; delete the nodes afterwards
    # if a conversation has been deleted, new updates will not be received
    # if a conversation is selected, then new updates will filter into the conversation list, and be processed accordingly
    while True:
        conversation_node, conversation_url = select_next_conversation_or_quit(
            driver, conversations)
        if conversation_node is None:
            break
        conversation_name = get_conversation_name(conversation_node)
        conversation_node.click()
        print("Parsing conversation ", conversation_url + ".")
        time.sleep(3)

        this_conversation = {
            "name": conversation_name,
            "messages": [],
        }
        conversations[conversation_url] = this_conversation
        scrape_conversation(SCREENSHOT_DIR, this_conversation, driver)

        # finished with conversation!
        # sort message_infos by datetime
        this_conversation["messages"].sort(key=lambda x: x["datetime"])
        save_conversations_json(CONVERSATIONS_FILE, conversations)

        # remove conversation from list by hiding it
        conversation_node_gp = conversation_node.find_element_by_xpath(
            "../..")
        driver.execute_script(
            "arguments[0].style.display = 'none';", conversation_node_gp)
        print("Finished conversation ", conversation_url + ".")
        time.sleep(3)


def try_close_driver(driver):
    try:
        driver.close()
        print("Closed driver.")
        return True
    except:
        print("Failed to close driver.")
        return False


def main(argv):
    """
    argv: List of command line arguments (sys.argv[1:])
    """
    opts = get_cmd_line_opts(argv)
    username, password = get_username_password(opts)
    CACHE_DIR = ".cache/"
    chromedriver_file = download_chromedriver(CACHE_DIR)
    USER_DATA_DIR = CACHE_DIR + "chrome-user-data/"
    driver = launch_chromedriver(USER_DATA_DIR, opts, chromedriver_file)
    if driver == None:
        return

    # save screenshots for debugging
    SCREENSHOT_DIR = CACHE_DIR + "screenshots/"
    pathlib.Path(SCREENSHOT_DIR).mkdir(parents=True, exist_ok=True)

    # begin scraping
    CONVERSATIONS_FILE = CACHE_DIR + "conversations.json"

    # conversations is a dictionary from urls (e.g. https://www.messenger.com/t/GilgameshxZero) to conversation_infos
    # conversation_infos are a dictionary with the following fields:
    # "name": string (name of conversation)
    # "messages": list of dictionaries (of message_infos)
    # message_infos are a dictionary with these fields:
    # "sender": string (of "self" or "them")
    # "datetime": string (of datetime)
    # "type": string (of "text", "sticker", "image", "file", or "other")
    # "content": string
    conversations = {}

    try:
        run_scraper(SCREENSHOT_DIR, CONVERSATIONS_FILE, username,
                    password, driver, conversations)
    except:
        traceback.print_exc()
        try:
            driver.save_screenshot(SCREENSHOT_DIR + "exception.png")
            print("Saved screenshot at exception.")
        except:
            pass
        # input("Pausing for debugging. Press enter to continue.")
    finally:
        try_close_driver(driver)

    save_conversations_json(CONVERSATIONS_FILE, conversations)


if __name__ == "__main__":
    main(sys.argv[1:])
