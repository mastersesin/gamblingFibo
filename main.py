import threading
import subprocess
import os
import logging
import time
import base64
from io import BytesIO

import numpy as np
from PIL import Image
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.common.exceptions import InvalidSelectorException, NoSuchElementException

import constants

logging.basicConfig(filename='app.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


class Worker(threading.Thread):
    def __init__(self, driver):
        super().__init__()
        self.driver = driver
        self.current_system_countdown = None
        self.gambling_result = {}
        self.our_gambling_result = True
        self.base_bet_value = 10
        self.bet_value = 0

    @staticmethod
    def classify_color(rgb):
        if rgb[0] == 4 and rgb[1] == 199 and rgb[2] == 147:
            return 1
        elif rgb[0] == 250 and rgb[1] == 75 and rgb[2] == 98:
            return 0
        elif rgb[0] == 47 and rgb[1] == 51 and rgb[2] == 66:
            return -1
        elif rgb[0] == 255 and rgb[1] == 255 and rgb[2] == 255:
            return -2
        return None

    @staticmethod
    def current_system_gambling_position(table_result):
        return len([x for x in table_result if x != -1])

    def login_checkpoint(self):
        while True:
            input('Connected! Please login and press enter...')
            try:
                last_result_elem = self.driver.find_element(By.XPATH, constants.last_result_tab)
                last_result_elem.click()
                break
            except (InvalidSelectorException, NoSuchElementException) as e:
                print('Check point failed!')
                logging.info("login_checkpoint - " + str(e))
                continue

    def load_gambling_table_result(self, table_xpath, delay=0):
        print(f"load_gambling_table_result call with delay <{delay}>")
        if delay:
            time.sleep(delay)
        table_elem = self.driver.find_element(By.XPATH, table_xpath)
        fourth_table_canvas_base64 = self.driver.execute_script(
            "return arguments[0].toDataURL('image/png').substring(21);",
            table_elem
        )
        canvas_png = base64.b64decode(fourth_table_canvas_base64)
        with BytesIO(canvas_png) as image_bytes:  # Use context manager for automatic cleanup
            image = Image.open(image_bytes)
            pixels = np.array(image)
            result = []
            for i, (x, y) in enumerate(constants.canvas_position):
                rgb = pixels[y, x]
                color = self.classify_color(rgb)
                if color is None:
                    logging.error("Something when wrong with color code on this machine")
                    raise TypeError("Something when wrong with color code on this machine")
                result.append(color)
            image.close()
        return result

    def time_tick_watcher(self):
        while True:
            try:
                time_tick_elem = self.driver.find_element(By.XPATH, constants.time_clock)
                self.current_system_countdown = int(time_tick_elem.text[:-1])
            except Exception as e:
                logging.info("time_tick_watcher - " + str(e))
            time.sleep(0.5)

    def remove_pop_up(self):
        try:
            elem = self.driver.find_element(By.XPATH, constants.congratulation_pop_up)
            self.driver.execute_script("""var element = arguments[0]; element.parentNode.removeChild(element);""", elem)
        except Exception:
            pass

    def win_or_lost_watcher(self, expected_result, position):
        print(f"win_or_lost_watcher called")
        fifth_table_result = self.load_gambling_table_result(
            table_xpath=constants.fifth_table,
            delay=self.current_system_countdown + 1 + 30  # Result for our current position
        )
        real_result = fifth_table_result[position]
        if expected_result == real_result:
            print("We won")
            self.remove_pop_up()
            self.our_gambling_result = True
        else:
            print("We lost")
            self.our_gambling_result = False
        return self.our_gambling_result

    def gambling_session(self, side, amount, result_position):
        print(f"Start new gambling session")
        self.driver.find_element(By.XPATH, constants.gambling_amount).clear()
        self.driver.find_element(By.XPATH, constants.gambling_amount).send_keys(amount)
        if side:
            print(f"Long position with {amount}$")
            self.driver.find_element(By.XPATH, constants.long_button).click()
        else:
            print(f"Short position with {amount}$")
            self.driver.find_element(By.XPATH, constants.short_button).click()
        return self.win_or_lost_watcher(expected_result=side, position=result_position)

    def calculate_bet_amount(self):
        if self.our_gambling_result:
            self.bet_value = self.base_bet_value
            return self.bet_value
        else:
            self.bet_value = self.bet_value * 2
            return self.bet_value

    def get_current_match_position(self, table_result):
        system_current_position = self.current_system_gambling_position(table_result)
        print(f"System current position at {system_current_position}")
        if system_current_position in constants.positions_on_fifth_table:
            return system_current_position
        return None

    def event_distribution_worker(self):
        while True:
            time.sleep(1)
            if not self.current_system_countdown:
                continue
            if not self.driver.find_element(By.XPATH, constants.long_button).is_enabled():
                time.sleep(35)
                continue
            fifth_table_result = self.load_gambling_table_result(constants.fifth_table)
            if self.current_system_gambling_position(fifth_table_result) > max(constants.positions_on_fifth_table):
                print(f"Current gambling position higher than all position configured will sleep {constants.duration}s!")
                time.sleep(constants.duration)
                self.our_gambling_result = True
                continue
            current_gambling_position = self.get_current_match_position(fifth_table_result)
            if current_gambling_position is None:
                time.sleep(35)
                print("Current gambling position not match will continue!")
                continue
            fourth_table_result = self.load_gambling_table_result(constants.fourth_table)
            # if (fourth_table_result[constants.main_pos_on_fourth_table] ==
            #         fifth_table_result[constants.compare_pos_on_fifth_table]):
            #     print("Pos 8 won will continue")
            #     continue
            self.gambling_session(
                side=fourth_table_result[constants.main_pos_on_fourth_table],
                amount=self.calculate_bet_amount(),
                result_position=current_gambling_position + 1
            )

    def run(self):
        self.driver.get('https://fibowin.com')
        self.login_checkpoint()
        threading.Thread(target=self.time_tick_watcher).start()
        threading.Thread(target=self.event_distribution_worker).start()
        print('Threads started!')


if __name__ == '__main__':
    current_dir = os.getcwd()
    cmd_string = (f'"{constants.chrome_bin_location}" '
                  f'--remote-debugging-port=9222 '
                  f'--user-data-dir={os.path.join(current_dir, "profile")}')
    subprocess.Popen(
        cmd_string,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE
    )
    chrome_options = Options()
    chrome_options.add_experimental_option(
        "debuggerAddress",
        f"{constants.remote_ip}:{constants.remote_debugging_port}"
    )
    web_driver = webdriver.Chrome(options=chrome_options)
    gambling_worker = Worker(driver=web_driver)
    gambling_worker.start()
