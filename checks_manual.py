##############################################################################################
# modules
##############################################################################################

import csv
import concurrent.futures
import time
from datetime import date
import schedule
import logging
import smtplib
import os
from email.message import EmailMessage
from ucm_cli import SSHConnect, parse_resp
from exp_cli import SSHConnectExp, parse_resp_exp
from email_settings import smtp_server, from_email, to_email, cc_email_1, cc_email_2
from exp_gui import expressway_alarm_cleanup

##############################################################################################
# Global Variables & Config
##############################################################################################

nodes_not_responding = []

nodes_high_uptime = []

nodes_stpd_srvs = []

nodes_expiring_certs = []

nodes_failed_backup = []

exp_alarms = []

##############################################################################################
# Functions
##############################################################################################

def core_checks():

    """
    Reads the server info from the infrastructure.csv.
    Creates a thread for each server returned from the csv and calls the _core_checks() inner function.

    """

    def _core_checks (node):

        """
        Inner function that creates an instance of SSHConnect() and calls the methods configured there in.

            : param node : The hostname or IP of the UCM, IM&P or CUC server.

        """


        logging.info('## {} - _core_checks({}) -- STARTING CHECKS'.format(__name__, node))

        ## Returns the username and password corresponding to the node from the csv.
        with open('infrastructure.csv') as f:
            for row in csv.DictReader(f):
                if node == row['hostname']:
                    role, username, password = row['role'], row['username'], row['password']

        ## Create the SSHConnect() instance, call its methods and records servers that fail the conditions to the
        ## 5 lists at the top of the script.
        try:
            conn = SSHConnect(node, username, password)
            logging.info('## {} - SSHConnect("{}")'.format(__name__, node))

            conn.init_connect()
            logging.debug('## {} - SSHConnect("{}").init_connect()'.format(__name__, node))


            try:
                conn.run_cmd('set cli pagination off')
                logging.debug('## {} - SSHConnect("{}").run_cmd()'.format(__name__, node))

            except Exception as e:
                logging.debug('## {} - SSHConnect("{}").run_cmd() -- EXCEPTION -- {}'.format(__name__, node, e))


            try:
                uptime, unit = conn.get_uptime()
                logging.debug('## {} - SSHConnect("{}").get_uptime()'.format(__name__, node))

                if 'days' in unit and int(uptime) >= 180:
                    logging.debug('## {} - SSHConnect("{}").get_uptime() -- {} {}'.format(__name__, node, uptime, unit))
                    nodes_high_uptime.append(node + ': ' + uptime + ' ' + unit)

            except Exception as e:
                logging.debug('## {} - SSHConnect("{}").get_uptime() -- EXCEPTION -- {}'.format(__name__, node, e))
                nodes_high_uptime.append(node + ': An exception occurred. Check node manually')


            try:
                stopped_srvs = conn.get_stopped_srvs(role)
                logging.debug('## {} - SSHConnect("{}").get_stopped_srvs() -- {}'.format(__name__, node, stopped_srvs))

                if len(stopped_srvs) >= 1:
                    nodes_stpd_srvs.append(node + ': ' + str(stopped_srvs))

            except Exception as e:
                logging.debug('## {} - SSHConnect("{}").get_stopped_srvs() -- EXCEPTION -- {}'.format(__name__, node, e))
                nodes_stpd_srvs.append(node + ': An exception occurred. Check node manually')    
            

            try:
                certs = conn.get_certs()
                logging.debug('## {} - SSHConnect("{}").get_certs() -- {}'.format(__name__, node, certs))

                for elem in certs:
                    if int(elem[3]) <= 28:
                        nodes_expiring_certs.append(node + ': ' + str(elem[0]) + ', ' + str(elem[2]))

            except Exception as e:
                logging.debug('## {} - SSHConnect("{}").get_certs() -- EXCEPTION -- {}'.format(__name__, node, e))
                nodes_expiring_certs.append(node + ': An exception occurred. Check node manually')


            if not role:
                logging.debug('## {} - SSHConnect("{}").get_backup() -- NOT PUBLISHER -- SKIPPING'.format(__name__, node))

            else:
                try:
                    backups = conn.get_backup()
                    logging.debug('## {} - SSHConnect("{}").get_backup() -- {}'.format(__name__, node, backups))

                    if 'ERROR' in backups[0]:
                        nodes_failed_backup.append(node + ': Last successful backp = ' + str(backups[1]) + ', Days since last backup = ' + str(backups[2]))

                except Exception as e:
                    logging.debug('## {} - SSHConnect("{}").get_backup() -- EXCEPTION -- {}'.format(__name__, node, e))
                    nodes_failed_backup.append(node + ': No DRF data available. Check node manually. Error = ' + str(e))


        except Exception as e:
            logging.debug('## {} - SSHConnect("{}") -- EXCEPTION -- {}'.format(__name__, node, e))
            nodes_not_responding.append(node + ': ' + str(e))

        try:
            conn.close_ssh()
            logging.debug('## {} - SSHConnect("{}").close_ssh()'.format(__name__, node))

        except Exception as e:
                logging.debug('## {} - SSHConnect("{}").close_ssh() -- EXCEPTION -- {}'.format(__name__, node, e))

        logging.info('## {} - _core_checks({}) -- UCM CHECKS COMPLETE'.format(__name__, node))


    logging.debug('## {} - core_checks() -- ENTERING FUNC'.format(__name__))

    ## Create a list of server hostnames from the csv.
    with open('infrastructure.csv') as f:
        hostnames = [row['hostname'] for row in csv.DictReader(f) if 'cte' not in row['region'] and 'exp' not in row['device']]

    ## Map each server in the hostnames[] list to the inner _core_checks() function and create a thread for it.
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        results = [ex.map(_core_checks, hostnames)]

        for f in results:

            return f

##############################################################################################


def exp_checks():

    def _exp_checks(node):

        with open('infrastructure.csv') as f:
            for row in csv.DictReader(f):
                if node == row['hostname']:
                    username, password = row['username'], row['password']

        try:
            expressway_alarm_cleanup(node, username, password)

        except Exception as e:
            logging.debug('## {} - expressway_alarm_cleanup("{}") -- EXCEPTION -- {}'.format(__name__, node, e))

        try:
            conn = SSHConnectExp(node, username, password)
            logging.debug('## {} - SSHConnectExp("{}")'.format(__name__, node))

            conn.init_connect()
            logging.debug('## {} - SSHConnectExp("{}").init_connect()'.format(__name__, node))

            try:
                if len(conn.run_cmd('xstatus alarm')) > 5:
                    exp_alarm_resp = node, conn.run_cmd('xstatus alarm')
                    exp_alarms.append(exp_alarm_resp)
                logging.debug('## {} - SSHConnectExp("{}").run_cmd()'.format(__name__, node))

            except Exception as e:
                logging.debug('## {} - SSHConnectExp("{}").run_cmd() -- EXCEPTION -- {}'.format(__name__, node, e))

        except Exception as e:
            logging.debug('## {} - SSHConnect("{}") -- EXCEPTION -- {}'.format(__name__, node, e))
            nodes_not_responding.append(node + ': ' + str(e))

        try:
            conn.close_ssh()
            logging.debug('## {} - SSHConnectExp("{}").close_ssh()'.format(__name__, node))

        except Exception as e:
                logging.debug('## {} - SSHConnectExp("{}").close_ssh() -- EXCEPTION -- {}'.format(__name__, node, e))

        logging.info('## {} - _core_checks({}) -- EXPRESSWAY CHECKS COMPLETE'.format(__name__, node))


    logging.debug('## {} - exp_checks() -- ENTERING FUNC'.format(__name__))

    with open('infrastructure.csv') as f:
        hostnames = [row['hostname'] for row in csv.DictReader(f) if 'exp' in row['device']]

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
        results = [ex.map(_exp_checks, hostnames)]

        for f in results:

            return f


##############################################################################################

def run_and_email():

    """
    Calls the core_checks() function, writes the results to a log file and to an email.

    """

    logging.info('## {} - run_and_email() -- STARTING CHECKS'.format(__name__))

    core_checks()

    exp_checks()

    today = date.today()

    results_file = f'uc_checks_{today}.txt'

    with open(results_file, 'a') as f:

        f.write('NODES NOT RESPONDING\n')
        f.write('='*len('NODES NOT RESPONDING'))
        f.write('\n')
        for elem in sorted(nodes_not_responding): f.write(str(elem) + '\n')
        f.write('\n\n')

        f.write('UCM NODES WITH STOPPED SERVICES\n')
        f.write('='*len('UCM NODES WITH STOPPED SERVICES'))
        f.write('\n')
        for elem in sorted(nodes_stpd_srvs): f.write(str(elem) + '\n')
        f.write('\n\n')

        f.write('UCM NODES WITH EXPIRING CERTS\n')
        f.write('='*len('UCM NODES WITH EXPIRING CERTS'))
        f.write('\n')
        for elem in sorted(nodes_expiring_certs): f.write(str(elem) + '\n')
        f.write('\n\n')

        f.write('UCM NODES WITH FAILED BACKUPS\n')
        f.write('='*len('UCM NODES WITH FAILED BACKUPS'))
        f.write('\n')
        for elem in sorted(nodes_failed_backup): f.write(str(elem) + '\n')
        f.write('\n\n')

        f.write('UCM NODES WITH UPTIME >180 DAYS\n')
        f.write('='*len('UCM NODES WITH UPTIME >180 DAYS'))
        f.write('\n')
        for elem in sorted(nodes_high_uptime): f.write(str(elem) + '\n')
        f.write('\n\n')

        f.write('EXPRESSWAY NODES WITH ALARMS\n')
        f.write('='*len('EXPRESSWAY NODES WITH ALARMS'))
        f.write('\n')
        for elem in sorted(exp_alarms):
            f.write(elem[0] + ':\n')
            f.write('*'*len(elem[0]) + '\n')
            for elem2 in elem[1][2:-5]:
                f.write(elem2 + '\n')
            f.write('\n\n')


    with open(results_file) as rf:
        msg = EmailMessage()
        msg.set_content(rf.read())

    msg['Subject'] = f'UC Morning Checks - {today}'
    msg['From'] = f'{from_email}'
    msg['To'] = f'{to_email}'
    msg['Bcc'] = f'{cc_email_1}, {cc_email_2}'
    #msg['To'] = f'{cc_email_1}'

    s = smtplib.SMTP(f'{smtp_server}')
    s.send_message(msg)
    s.quit()

    del nodes_not_responding[:]
    del nodes_high_uptime[:]
    del nodes_stpd_srvs[:]
    del nodes_expiring_certs[:]
    del nodes_failed_backup[:]
    del exp_alarms[:]
    logging.info('## {} - run_and_email() -- RESULTS LISTS CLEARED'.format(__name__))

    os.remove(results_file)
    logging.info('## {} - run_and_email() -- RESULTS FILE REMOVED'.format(__name__))

    logging.info('## {} - run_and_email() -- ALL CHECKS COMPLETE'.format(__name__))


##############################################################################################

def scheduler(start_time):

    """
    Small function to schedule when the script will be run.

        : param start_time: The time of day the script will be run.

    """

    schedule.every().day.at(start_time).do(run_and_email)

    while True:
        schedule.run_pending()
        time.sleep(1)


##############################################################################################
# Run
##############################################################################################

if __name__ == '__main__':

    format = "%(asctime)s: %(message)s"
    logging.basicConfig(format=format, level=logging.INFO, datefmt="%H:%M:%S")

    run_and_email()