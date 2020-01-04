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

# use the correct chromedriver for your chrome version!
CHROMEDRIVER_URL = "https://chromedriver.storage.googleapis.com/79.0.3945.36/chromedriver_win32.zip"


def main(argv):
    """
    argv: List of command line arguments (sys.argv[1:])
    """
    # parse command line arguments
    try:
        opts, args = getopt.getopt(
            argv, "", ["username=", "password=", "headless"])
        opts = {opt[0]: opt[1] for opt in opts}
    except:
        print("Error parsing command-line arguments. Continuing...")
        opts = {}

    # get username and password
    username = opts["--username"] if "--username" in opts.keys() else \
        input("Messenger username: ")
    password = opts["--password"] if "--password" in opts.keys() else \
        getpass.getpass("Messenger password: ")

    # download chromedriver
    CACHE_DIR = ".cache/"

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

    # setup driver
    try:
        USER_DATA_DIR = CACHE_DIR + "chrome-user-data/"
        chrome_options = selenium.webdriver.chrome.options.Options()
        chrome_options.add_argument("--user-data-dir=" + USER_DATA_DIR)
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--window-size=1920,1080")
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
    except:
        traceback.print_exc()
        print("Failed to launch driver.")
        return

    # save screenshots for debugging
    SCREENSHOT_DIR = CACHE_DIR + "screenshots/"
    pathlib.Path(SCREENSHOT_DIR).mkdir(parents=True, exist_ok=True)

    # begin scraping
    try:
        driver.get("https://www.messenger.com/")
        driver.save_screenshot(SCREENSHOT_DIR + "login.png")

        # try to login
        try:
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
            time.sleep(5)
            print("Logged in.")
        except:
            print("Did not log in (check screenshots for info).")
        driver.save_screenshot(SCREENSHOT_DIR + "main.png")

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

        # count of "other" types of messages
        other_count = 0

        # go through each conversation in order; delete the nodes afterwards
        # if a conversation has been deleted, new updates will not be received
        # if a conversation is selected, then new updates will filter into the conversation list, and be processed accordingly
        while True:
            conversation_list = driver.find_element_by_css_selector(
                "ul[aria-label='Conversation List']")
            conversation_nodes = conversation_list.find_elements_by_css_selector(
                "li>div>a[role='link']")
            if len(conversation_nodes) < 1:
                print("No more conversations. Terminating...")
                break

            # get url identifying the first visible conversation
            for conversation_node in conversation_nodes:
                display = driver.execute_script(
                "return arguments[0].parentNode.parentNode.style.display;", conversation_node)
                if display != "none":
                    break
            conversation_url = conversation_node.get_attribute("data-href")
            conversation_name = conversation_node.find_element_by_css_selector("div[data-tooltip-content]").get_attribute(
                "data-tooltip-content")
            conversation_node.click()
            time.sleep(3)
            print("Parsing conversation ", conversation_url + ".")

            if conversation_url in conversations:
                # then this probably is a result of a retry, so we can skip this conversation
                print("Found", conversation_url, "in conversations already. Skipping...")
            else:
                conversations[conversation_url] = {
                    "name": conversation_name,
                    "messages": [],
                }

                # begin parsing messages
                while True:
                    # this conversation is done only when no more top level divs
                    message_groups = driver.find_elements_by_css_selector(
                        "div[aria-label='Messages']>div>*")
                    if len(message_groups) < 1:
                        break

                    # parse this message_group before deleting it
                    message_group = message_groups[-1]

                    # if is not div element, remove it and skip it!
                    tag_name = driver.execute_script(
                        "return arguments[0].tagName;", message_group)
                    if tag_name.lower() != "div":
                        driver.execute_script(
                            "arguments[0].remove();", message_group)
                        time.sleep(1)
                        continue

                    divs_with_tooltips = message_group.find_elements_by_css_selector(
                        "div[data-tooltip-content]")
                    for div_with_tooltip in divs_with_tooltips:
                        message_by_self = div_with_tooltip.get_attribute(
                            "data-tooltip-position") == "right"
                        message_time = div_with_tooltip.get_attribute(
                            "data-tooltip-content")
                        # if the tooltip isn't a time, then this isn't a message!
                        try:
                            message_datetime = parser.parse(message_time)
                        except:
                            continue

                        # try to parse type of message
                        try:
                            message_divs = div_with_tooltip.find_elements_by_css_selector(
                                "div[aria-label]")
                            if len(message_divs) < 1:
                                # file or image
                                # test if not image
                                presentation_divs = div_with_tooltip.find_elements_by_css_selector(
                                    "div[role='presentation']")
                                if len(presentation_divs) < 1:
                                    message_type = "file"
                                    message_content = div_with_tooltip.find_element_by_css_selector(
                                        "a[data-lynx-mode='hover']").get_attribute("href")
                                else:
                                    message_type = "image"
                                    presentation_div = presentation_divs[0]
                                    message_content = presentation_div.find_element_by_css_selector(
                                        "img").get_attribute("src")
                            else:
                                # text or sticker
                                message_div = message_divs[0]
                                message_content = message_div.get_attribute(
                                    "aria-label")

                                # if has data-testid attribute, then it is a sticker
                                if driver.execute_script("return arguments[0].hasAttribute('data-testid');", message_div):
                                    message_type = "sticker"
                                else:
                                    message_type = "text"
                        except:
                            driver.save_screenshot(
                                SCREENSHOT_DIR + "unparsed-" + str(other_count) + ".png")
                            other_count += 1
                            print("Could not parse message type (" + str(other_count) +
                                  ")! Screenshot saved. Post saved as other.")
                            message_type = "other"
                            message_content = ""

                        # create message_info
                        message_info = {
                            "sender": "self" if message_by_self else "them",
                            "datetime": message_datetime,
                            "type": message_type,
                            "content": message_content,
                        }
                        print("Me:" if message_by_self else "Them:", message_content)
                        conversations[conversation_url]["messages"].append(message_info)

                    # delete this message_group
                    driver.execute_script("arguments[0].remove();", message_group)
                    # print("Deleted message group.")
                    time.sleep(1)

                # sort message_infos by datetime
                conversations[conversation_url]["messages"].sort(key=lambda x: x["datetime"])

            # remove conversation from list by hiding it
            # this might break, again; so just retry if it does
            conversation_node_gp = conversation_node.find_element_by_xpath(
                "../..")
            driver.execute_script(
                "arguments[0].style.display = 'none';", conversation_node_gp)
            print("Finished conversation ", conversation_url + ".")
            time.sleep(3)
    except:
        traceback.print_exc()
        try:
            driver.save_screenshot(SCREENSHOT_DIR + "exception.png")
            print("Saved screenshot at exception.")
            print("message_group:", message_group.get_attribute("outerHTML"))
            print("message_divs:", message_divs.get_attribute("outerHTML"))
        except:
            pass
        input("Pausing for debugging. Press enter to continue.")
    finally:
        try:
            driver.close()
            print("Closed driver.")
        except:
            print("Failed to close driver. Continuing...")

    CONVERSATIONS_FILE = CACHE_DIR + "conversations.json"
    with open(CONVERSATIONS_FILE, "w") as file:
        json.dump(conversations, file, indent=2, default=str)
    print("Saved conversations JSON.")


if __name__ == "__main__":
    main(sys.argv[1:])
