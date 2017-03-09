﻿# -*- coding: utf-8 -*-

import sys, os
p = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if p not in sys.path:
    sys.path.insert(0, p)

import random, pickle, time, requests
from collections import defaultdict

from qqbot.qconf import QConf
from qqbot.qrcodemanager import QrcodeManager
from qqbot.messagefactory import Task
from qqbot.qcontacts import QContactDB, BuddyList, GroupList
from qqbot.qcontacts import DiscussList, MemberList
from qqbot.common import JsonLoads, JsonDumps
from qqbot.utf8logger import CRITICAL, ERROR, WARN, INFO
from qqbot.utf8logger import DEBUG, DisableLog, EnableLog
from qqbot.exitcode import QSESSION_ERROR
from qqbot.common import PY3

def QLogin(qq=None, user=None, conf=None):
    if conf is None:        
        conf = QConf(qq, user)

    if conf.qq:
        INFO('开始自动登录...')
        picklePath = conf.PicklePath()
        try:
            session, contacts = restore(picklePath)
        except Exception as e:
            WARN('自动登录失败，原因：%s', e, exc_info=True)
        else:
            INFO('成功从文件 "%s" 中恢复登录信息和联系人' % picklePath)
            try:
                session.TestLogin()
            except QSession.Error:
                WARN('自动登录失败，原因：上次保存的登录信息已过期')
            else:
                return session, contacts

    INFO('开始手动登录...')
    session = QSession()
    contacts = session.Login(conf)
    return session, contacts

def restore(picklePath):
    with open(picklePath, 'rb') as f:
        return pickle.load(f)

def dump(picklePath, session, contacts):
    try:
        with open(picklePath, 'wb') as f:
            pickle.dump((session, contacts), f)
    except IOError:
        WARN('保存登录信息及联系人失败：IOError %s', picklePath)
    else:
        INFO('登录信息及联系人已保存至文件：file://%s' % picklePath)

class QSession(object):

    class Error(SystemExit):
        def __init__(self):
            SystemExit.__init__(self, QSESSION_ERROR)

    def Login(self, conf):        
        self.prepareSession()
        self.waitForAuth(conf)
        self.getPtwebqq()
        self.getVfwebqq()
        self.getUinAndPsessionid()
        self.TestLogin()
        return self.fetch(conf.PicklePath())

    def prepareSession(self):
        self.clientid = 53999199
        self.msgId = 6000000
        self.lastSendTime = 0
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10.9;'
                           ' rv:27.0) Gecko/20100101 Firefox/27.0'),
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'
        })
        self.urlGet(
            'https://ui.ptlogin2.qq.com/cgi-bin/login?daid=164&target=self&'
            'style=16&mibao_css=m_webqq&appid=501004106&enable_qlogin=0&'
            'no_verifyimg=1&s_url=http%3A%2F%2Fw.qq.com%2Fproxy.html&'
            'f_url=loginerroralert&strong_login=1&login_state=10&t=20131024001'
        )
        self.session.cookies.update({
            'RK': 'OfeLBai4FB',
            'pgv_pvi': '911366144',
            'pgv_info': 'ssid pgv_pvid=1051433466',
            'ptcz': ('ad3bf14f9da2738e09e498bfeb93dd9da7'
                     '540dea2b7a71acfb97ed4d3da4e277'),
            'qrsig': ('hJ9GvNx*oIvLjP5I5dQ19KPa3zwxNI'
                      '62eALLO*g2JLbKPYsZIRsnbJIxNe74NzQQ')
        })
        self.getAuthStatus()
        self.session.cookies.pop('qrsig')
    
    def Copy(self):
        c = QSession()
        c.__dict__.update(self.__dict__)
        c.session = pickle.loads(pickle.dumps(c.session))
        return c

    def getQrcode(self):
        qrcode = self.urlGet(
            'https://ssl.ptlogin2.qq.com/ptqrshow?appid=501004106&e=0&l=M&' +
            's=5&d=72&v=4&t=' + repr(random.random())
        ).content
        INFO('已获取二维码')
        return qrcode

    def waitForAuth(self, conf):
        qrcodeManager = QrcodeManager(conf)
        try:
            qrcodeManager.Show(self.getQrcode())
            while True:
                time.sleep(3)
                authStatus = self.getAuthStatus()
                if '二维码未失效' in authStatus:
                    INFO('等待二维码扫描及授权')
                elif '二维码认证中' in authStatus:
                    INFO('二维码已扫描，等待授权')
                elif '二维码已失效' in authStatus:
                    WARN('二维码已失效, 重新获取二维码')
                    qrcodeManager.Show(self.getQrcode())
                elif '登录成功' in authStatus:
                    INFO('已获授权')
                    items = authStatus.split(',')
                    self.nick = str(items[-1].split("'")[1])
                    self.qq = str(int(self.session.cookies['superuin'][1:]))
                    self.urlPtwebqq = items[2].strip().strip("'")
                    conf.qq = self.qq
                    break
                else:
                    CRITICAL('获取二维码扫描状态时出错, html="%s"', authStatus)
                    sys.exit(1)
        finally:
            qrcodeManager.Destroy()

    def getAuthStatus(self):
        # by @zofuthan
        result = self.urlGet(
            url='https://ssl.ptlogin2.qq.com/ptqrlogin?ptqrtoken=' + 
                str(bknHash(self.session.cookies['qrsig'], init_str=0)) +
                '&webqq_type=10&remember_uin=1&login2qq=1&aid=501004106' +
                '&u1=http%3A%2F%2Fw.qq.com%2Fproxy.html%3Flogin2qq%3D1%26' +
                'webqq_type%3D10&ptredirect=0&ptlang=2052&daid=164&' +
                'from_ui=1&pttype=1&dumy=&fp=loginerroralert&action=0-0-' +
                repr(random.random() * 900000 + 1000000) +
                '&mibao_css=m_webqq&t=undefined&g=1&js_type=0' +
                '&js_ver=10141&login_sig=&pt_randsalt=0',
            Referer=('https://ui.ptlogin2.qq.com/cgi-bin/login?daid=164&'
                     'target=self&style=16&mibao_css=m_webqq&appid=501004106&'
                     'enable_qlogin=0&no_verifyimg=1&s_url=http%3A%2F%2F'
                     'w.qq.com%2Fproxy.html&f_url=loginerroralert&'
                     'strong_login=1&login_state=10&t=20131024001')
        ).content
        return result if not PY3 else result.decode('utf8')

    def getPtwebqq(self):
        self.urlGet(self.urlPtwebqq)
        self.ptwebqq = self.session.cookies['ptwebqq']
        INFO('已获取ptwebqq')

    def getVfwebqq(self):
        self.vfwebqq = self.smartRequest(
            url = ('http://s.web2.qq.com/api/getvfwebqq?ptwebqq=%s&'
                   'clientid=%s&psessionid=&t={rand}') %
                  (self.ptwebqq, self.clientid),
            Referer = ('http://s.web2.qq.com/proxy.html?v=20130916001'
                       '&callback=1&id=1'),
            Origin = 'http://s.web2.qq.com'
        )['vfwebqq']
        INFO('已获取vfwebqq')

    def getUinAndPsessionid(self):
        result = self.smartRequest(
            url = 'http://d1.web2.qq.com/channel/login2',
            data = {
                'r': JsonDumps({
                    'ptwebqq': self.ptwebqq, 'clientid': self.clientid,
                    'psessionid': '', 'status': 'online'
                })
            },
            Referer = ('http://d1.web2.qq.com/proxy.html?v=20151105001'
                       '&callback=1&id=2'),
            Origin = 'http://d1.web2.qq.com'
        )
        self.uin = result['uin']
        self.psessionid = result['psessionid']
        self.hash = qHash(self.uin, self.ptwebqq)
        self.bkn = bknHash(self.session.cookies['skey'])
        INFO('已获取uin和psessionid')

    def TestLogin(self):
        try:
            DisableLog()
            # 请求一下 get_online_buddies 页面，避免103错误。
            # 若请求无错误发生，则表明登录成功
            self.smartRequest(
                url = ('http://d1.web2.qq.com/channel/get_online_buddies2?'
                       'vfwebqq=%s&clientid=%d&psessionid=%s&t={rand}') %
                      (self.vfwebqq, self.clientid, self.psessionid),
                Referer = ('http://d1.web2.qq.com/proxy.html?v=20151105001&'
                           'callback=1&id=2'),
                Origin = 'http://d1.web2.qq.com',
                repeateOnDeny = 0
            )
        finally:
            EnableLog()
        
        INFO('登录成功。登录账号：%s(%s)', self.nick, self.qq)
    
    def fetch(self, picklePath):
        contacts = QContactDB()
        for task in self.Fetch(contacts, picklePath, None):
            task.Exec()
        return contacts

    def Fetch(self, contacts, picklePath, bot):
        try:
            bl = self.fetchBuddyList()
        except (Exception, QSession.Error) as e:
            WARN('获取好友列表出错: %s', e)
            DEBUG('', exc_info=True)
        else:
            yield Task(contacts.SetBuddyList, bl, bot)
            yield Task(INFO, '已更新好友列表，共 %s 个好友', len(bl))
        
        try:
            gl = self.fetchGroupList()
        except (Exception, QSession.Error) as e:
            WARN('获取群列表出错！: %s', e)
            DEBUG('', exc_info=True)
        else:
            for group in gl:
                try:
                    group.memberList = self.fetchGroupMemberList(group)
                except (Exception, QSession.Error) as e:
                    WARN('获取 %s 的成员列表出错: %s', group, e)
                    DEBUG('', exc_info=True)
                    group.memberList = MemberList()
                else:
                    if bot is None: # first fetch
                        yield Task(INFO, '已更新 %s 的成员列表', group)

            yield Task(contacts.SetGroupList, gl, bot)
            yield Task(INFO, '已更新群列表，共 %s 个群', len(gl))

        try:
            dl = self.fetchDiscussList()
        except (Exception, QSession.Error) as e:
            WARN('获取讨论组列表出错！: %s', e)
            DEBUG('', exc_info=True)
        else:
            for discuss in dl:
                try:
                    discuss.memberList = \
                        self.fetchDiscussMemberList(discuss)
                except (Exception, QSession.Error) as e:
                    WARN('获取 %s 的成员列表出错！: %s', discuss, e)
                    DEBUG('', exc_info=True)
                    discuss.memberList = MemberList()
                else:
                    if bot is None: # first fetch
                        yield Task(INFO, '已更新 %s 的成员列表', discuss)

            yield Task(contacts.SetDiscussList, dl, bot)
            yield Task(INFO, '已更新讨论组列表，共 %s 个群', len(dl))
        
        yield Task(dump, picklePath, self, contacts)

    def fetchBuddyList(self):        
        result = self.smartRequest(
            url = 'http://s.web2.qq.com/api/get_user_friends2',
            data = {
                'r': JsonDumps({'vfwebqq':self.vfwebqq, 'hash':self.hash})
            },
            Referer = ('http://d1.web2.qq.com/proxy.html?v=20151105001&'
                       'callback=1&id=2')
        )

        markDict = dict((d['uin'],d['markname']) for d in result['marknames'])
        
        qqResult = self.smartRequest(
            url = 'http://qun.qq.com/cgi-bin/qun_mgr/get_friend_list',
            data = {'bkn': self.bkn},
            Referer = 'http://qun.qq.com/member.html'
        )
        qqDict = defaultdict(list)
        for blist in list(qqResult.values()):
            for d in blist.get('mems', []):
                name = d['name'].replace('&nbsp;', ' ').replace('&amp;', '&')
                qqDict[name].append(d['uin'])
        
        buddyList = BuddyList()

        for info in result['info']:
            uin = info['uin']
            nick = info['nick']
            mark = markDict.get(uin, '')
            name = mark or nick
            qqlist = qqDict.get(name, [])
            if len(qqlist) == 1:
                qq = qqlist.pop()
            else:
                qq = self.fetchBuddyQQ(uin)
                try:
                    qqlist.remove(qq)
                except ValueError:
                    pass
                
            buddyList.Add(str(uin), name, qq=str(qq), mark=mark, nick=nick)
        
        return buddyList

    def fetchBuddyQQ(self, uin):
        return self.smartRequest(
            url = ('http://s.web2.qq.com/api/get_friend_uin2?tuin=%s&'
                   'type=1&vfwebqq=%s&t={rand}') % (uin, self.vfwebqq),
            Referer = ('http://d1.web2.qq.com/proxy.html?v=20151105001&'
                       'callback=1&id=2'),
            timeoutRetVal = {'account': ''}
        )['account']

    def fetchGroupList(self):
        result = self.smartRequest(
            url = 'http://s.web2.qq.com/api/get_group_name_list_mask2',
            data = {
                'r': JsonDumps({'vfwebqq':self.vfwebqq, 'hash':self.hash})
            },
            Referer = ('http://d1.web2.qq.com/proxy.html?v=20151105001&'
                       'callback=1&id=2'),
            resultChecker = lambda r: ('gmarklist' in r),
            repeateOnDeny = 5
        )
         
        markDict = dict((d['uin'],d['markname']) for d in result['gmarklist'])

        qqResult = self.smartRequest(
            url = 'http://qun.qq.com/cgi-bin/qun_mgr/get_group_list',
            data = {'bkn': self.bkn},
            Referer = 'http://qun.qq.com/member.html'
        )
        
        qqDict = defaultdict(list)
        for k in ('create', 'manage', 'join'):
            for d in qqResult.get(k, []):
                name = d['gn'].replace('&nbsp;', ' ').replace('&amp;', '&')
                qqDict[name].append(d['gc'])
        
        groupList = GroupList()

        for info in result['gnamelist']:
            uin = info['gid']
            name = info['name']
            mark = markDict.get(uin, '')

            qqlist = qqDict.get(name, [])
            if len(qqlist) == 1:
                qq = qqlist.pop()
            else:
                qq = self.fetchGroupQQ(uin)
                for x in qqlist:
                    if (qq - x) % 1000000 == 0:
                        qq = x
                        break
                try:
                    qqlist.remove(qq)
                except ValueError:
                    pass

            groupList.Add(str(uin), name, qq=str(qq),
                          mark=mark, gcode=info['code'])
        
        return groupList
    
    def fetchGroupQQ(self, uin):
        return self.smartRequest(
            url = ('http://s.web2.qq.com/api/get_friend_uin2?tuin=%s&'
                   'type=4&vfwebqq=%s&t={rand}') % (uin, self.vfwebqq),
            Referer = ('http://d1.web2.qq.com/proxy.html?v=20151105001&'
                       'callback=1&id=2'),
            timeoutRetVal = {'account': ''}
        )['account']
    
    def fetchGroupMemberList(self, group):

        def extractor(result):
            retcode = result.get('retcode', -1)
            if retcode == 0:
                pass
            elif retcode == 6:
                for m in result['result']['ginfo']['members']:
                    group.memberList.Add(str(m['muin']), '##UNKOWN')
        
        
        
        self.smartRequest(
            url = ('http://s.web2.qq.com/api/get_group_info_ext2?gcode=%s'
                   '&vfwebqq=%s&t={rand}') % (group.gcode, self.vfwebqq),
            Referer = ('http://s.web2.qq.com/proxy.html?v=20130916001'
                       '&callback=1&id=1')
        )
        
        ret['minfo'] = ret.get(
            'minfo', [{'nick': '##UNKNOWN'}] * len(ret['ginfo']['members'])
        )
        
        for m, inf in zip(ret['ginfo']['members'], ret['minfo']):
            memberList.Add(str(m['muin']), str(inf['nick']), owner=group)

    def fetchDiscussList(self):
        result = self.smartRequest(
            url = ('http://s.web2.qq.com/api/get_discus_list?clientid=%s&'
                   'psessionid=%s&vfwebqq=%s&t={rand}') % 
                  (self.clientid, self.psessionid, self.vfwebqq),
            Referer = ('http://d1.web2.qq.com/proxy.html?v=20151105001'
                       '&callback=1&id=2')
        )['dnamelist']
        discussList = DiscussList()
        for info in result:
            discussList.Add(str(info['did']), str(info['name']))
        return discussList
    
    def fetchDiscussMemberList(self, discuss):
        ret = self.smartRequest(
            url = ('http://d1.web2.qq.com/channel/get_discu_info?'
                   'did=%s&psessionid=%s&vfwebqq=%s&clientid=%s&t={rand}') %
                  (discuss.uin, self.psessionid, self.vfwebqq, self.clientid),
            Referer = ('http://d1.web2.qq.com/proxy.html?v=20151105001'
                       '&callback=1&id=2')
        )
        memberList = MemberList()
        for m in ret['mem_info']:
            memberList.Add(str(m['uin']), str(m['nick']), owner=discuss)
        return memberList

    def Poll(self):
        result = self.smartRequest(
            url = 'https://d1.web2.qq.com/channel/poll2',
            data = {
                'r': JsonDumps({
                    'ptwebqq':self.ptwebqq, 'clientid':self.clientid,
                    'psessionid':self.psessionid, 'key':''
                })
            },
            Referer = ('http://d1.web2.qq.com/proxy.html?v=20151105001&'
                       'callback=1&id=2')
        )

        if not result or 'errmsg' in result:
            return 'timeout', '', '', ''
        else:
            result = result[0]
            ctype = {
                'message': 'buddy',
                'group_message': 'group',
                'discu_message': 'discuss'
            }[result['poll_type']]
            fromUin = str(result['value']['from_uin'])
            memberUin = str(result['value'].get('send_uin', ''))
            content = ''.join(
                ('[face%d]' % m[1]) if isinstance(m, list) else str(m)
                for m in result['value']['content'][1:]
            )
            return ctype, fromUin, memberUin, content

    def Send(self, ctype, uin, content):
        self.msgId += 1
        sendUrl = {
            'buddy': 'http://d1.web2.qq.com/channel/send_buddy_msg2',
            'group': 'http://d1.web2.qq.com/channel/send_qun_msg2',
            'discuss': 'http://d1.web2.qq.com/channel/send_discu_msg2'
        }
        sendTag = {'buddy':'to', 'group':'group_uin', 'discuss':'did'}
        self.smartRequest(
            url = sendUrl[ctype],
            data = {
                'r': JsonDumps({
                    sendTag[ctype]: int(uin),
                    'content': JsonDumps([
                        content,
                        ['font', {'name': '宋体', 'size': 10,
                                  'style': [0,0,0], 'color': '000000'}]
                    ]),
                    'face': 522,
                    'clientid': self.clientid,
                    'msg_id': self.msgId,
                    'psessionid': self.psessionid
                })
            },
            Referer = ('http://d1.web2.qq.com/proxy.html?v=20151105001&'
                       'callback=1&id=2'),
            repeateOnDeny=5
        )

    def urlGet(self, url, data=None, **kw):
        self.session.headers.update(kw)
        try:
            if data is None:
                return self.session.get(url)
            else:
                return self.session.post(url, data=data)
        except (requests.exceptions.SSLError, AttributeError):
            # by @staugur, @pandolia
            if self.session.verify:
                time.sleep(5)
                ERROR('无法和腾讯服务器建立私密连接，'
                      ' 15 秒后将尝试使用非私密连接和腾讯服务器通讯。'
                      '若您不希望使用非私密连接，请按 Ctrl+C 退出本程序。')
                time.sleep(15)
                WARN('开始尝试使用非私密连接和腾讯服务器通讯。')
                self.session.verify = False
                requests.packages.urllib3.disable_warnings(
                    requests.packages.urllib3.exceptions.
                    InsecureRequestWarning
                )
                return self.urlGet(url, data, **kw)
            else:
                raise

    def smartRequest(self, url, data=None, timeoutRetVal=None,
                     resultExtractor=None, repeateOnDeny=2, **kw):
        nCE, nTO, nUE, nDE = 0, 0, 0, 0
        while True:
            url = url.format(rand=repr(random.random()))
            html = ''
            errorInfo = ''
            try:
                resp = self.urlGet(url, data, **kw)
            except requests.ConnectionError as e:
                nCE += 1
                errorInfo = '网络错误 %s' % e
            else:
                html = resp.content if not PY3 else resp.content.decode('utf8')
                if resp.status_code in (502, 504, 404):
                    self.session.get(
                        ('http://pinghot.qq.com/pingd?dm=w.qq.com.hot&'
                         'url=/&hottag=smartqq.im.polltimeout&hotx=9999&'
                         'hoty=9999&rand=%s') % random.randint(10000, 99999)
                    )
                    if url == 'https://d1.web2.qq.com/channel/poll2':
                        return {'errmsg': ''}
                    nTO += 1
                    errorInfo = '超时'
                else:
                    try:
                        result = JsonLoads(html)
                    except ValueError:
                        nUE += 1
                        errorInfo = ' URL 地址错误'
                    else:
                        if resultExtractor:
                            result = resultExtractor(result)
                            if result:
                                return result                        
                        else:
                            if 'retcode' in result:
                                retcode = result['retcode']
                            elif 'errCode' in result:
                                retcode = result('errCode')
                            elif 'ec' in result:
                                retcode = result['ec']
                            else:
                                retcode = -1
                            if retcode in (0, 100003, 100100):
                                return result.get('result', result)

                        nDE += 1
                        errorInfo = '请求被拒绝错误'

            # 出现网络错误、超时、 URL 地址错误可以多试几次 
            # 若网络没有问题但 retcode 有误，一般连续 3 次都出错就没必要再试了
            if nCE < 5 and nTO < 20 and nUE < 5 and nDE <= repeateOnDeny:
                DEBUG('第%d次请求“%s”时出现“%s”, html=%s',
                      nCE+nTO+nUE+nDE, url, errorInfo, repr(html))
                time.sleep(0.5)
            elif nTO == 20 and timeoutRetVal: # by @killerhack
                return timeoutRetVal
            else:
                CRITICAL('第%d次请求“%s”时出现“%s”',
                         nCE+nTO+nUE+nDE, url, errorInfo)
                raise QSession.Error

def qHash(x, K):
    N = [0] * 4
    for T in range(len(K)):
        N[T%4] ^= ord(K[T])

    U, V = 'ECOK', [0] * 4
    V[0] = ((x >> 24) & 255) ^ ord(U[0])
    V[1] = ((x >> 16) & 255) ^ ord(U[1])
    V[2] = ((x >>  8) & 255) ^ ord(U[2])
    V[3] = ((x >>  0) & 255) ^ ord(U[3])

    U1 = [0] * 8
    for T in range(8):
        U1[T] = N[T >> 1] if T % 2 == 0 else V[T >> 1]

    N1, V1 = '0123456789ABCDEF', ''
    for aU1 in U1:
        V1 += N1[((aU1 >> 4) & 15)]
        V1 += N1[((aU1 >> 0) & 15)]

    return V1

def bknHash(skey, init_str=5381):
    hash_str = init_str
    for i in skey:
        hash_str += (hash_str << 5) + ord(i)
    hash_str = int(hash_str & 2147483647)
    return hash_str

if __name__ == '__main__':
    session, contacts = QLogin(conf=QConf())
