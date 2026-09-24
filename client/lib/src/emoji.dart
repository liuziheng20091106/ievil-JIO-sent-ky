// 由 temp/gen_emoji.py 从 QFace 表情索引生成，请勿手改。
// 图片来自 QFace（MIT）的 public/static/s<id>.png，只取经典 275 张与超级 50 张静态图。
import 'package:flutter/material.dart';

/// 一条静态 QQ 表情：[id] 是资源文件名，[name] 同时是 `[/名字]` token 的解析键。
@immutable
class EmojiFace {
  const EmojiFace(this.id, this.name, this.pinyin, this.superFace);

  final String id;
  final String name;

  /// 经典表情的拼音全拼与首字母缩写；超级表情没有官方输入码，为空。
  final List<String> pinyin;
  final bool superFace;

  String get asset => 'assets/emoji/qq/$id.png';
  String get token => '[/$name]';
}

/// 表情总表：经典在前、超级在后，顺序即面板里的展示顺序。
const emojiFaces = <EmojiFace>[
  EmojiFace('0', '惊讶', ['jingya', 'jy'], false),
  EmojiFace('1', '撇嘴', ['piezui', 'pz'], false),
  EmojiFace('2', '色', ['se'], false),
  EmojiFace('3', '发呆', ['fadai', 'fd'], false),
  EmojiFace('4', '得意', ['deyi', 'dy'], false),
  EmojiFace('5', '流泪', ['liulei', 'll'], false),
  EmojiFace('6', '害羞', ['haixiu', 'hx'], false),
  EmojiFace('7', '闭嘴', ['bizui', 'bz'], false),
  EmojiFace('8', '睡', ['shui'], false),
  EmojiFace('9', '大哭', ['daku', 'dk'], false),
  EmojiFace('10', '尴尬', ['ganga', 'gg'], false),
  EmojiFace('11', '发怒', ['fanu', 'fn'], false),
  EmojiFace('12', '调皮', ['tiaopi', 'tp'], false),
  EmojiFace('13', '呲牙', ['ziya', 'zy'], false),
  EmojiFace('14', '微笑', ['weixiao', 'wx'], false),
  EmojiFace('15', '难过', ['nanguo', 'ng'], false),
  EmojiFace('16', '酷', ['ku'], false),
  EmojiFace('18', '抓狂', ['zhuakuang', 'zk'], false),
  EmojiFace('19', '吐', ['tu'], false),
  EmojiFace('20', '偷笑', ['touxiao', 'tx'], false),
  EmojiFace('21', '可爱', ['keai', 'ka'], false),
  EmojiFace('22', '白眼', ['baiyan', 'by'], false),
  EmojiFace('23', '傲慢', ['aoman', 'am'], false),
  EmojiFace('24', '饥饿', ['jie', 'je'], false),
  EmojiFace('25', '困', ['kun'], false),
  EmojiFace('26', '惊恐', ['jingkong', 'jk'], false),
  EmojiFace('27', '流汗', ['liuhan', 'lh'], false),
  EmojiFace('28', '憨笑', ['hanxiao', 'hx'], false),
  EmojiFace('29', '悠闲', ['youxian', 'yx'], false),
  EmojiFace('30', '奋斗', ['fendou', 'fd'], false),
  EmojiFace('31', '咒骂', ['zhouma', 'zm'], false),
  EmojiFace('32', '疑问', ['yiwen', 'yw'], false),
  EmojiFace('33', '嘘', ['xu'], false),
  EmojiFace('34', '晕', ['yun'], false),
  EmojiFace('35', '折磨', ['zhemo', 'zm'], false),
  EmojiFace('36', '衰', ['shuai'], false),
  EmojiFace('37', '骷髅', ['kulou', 'kl'], false),
  EmojiFace('38', '敲打', ['qiaoda', 'qd'], false),
  EmojiFace('39', '再见', ['zaijian', 'zj'], false),
  EmojiFace('41', '发抖', ['fadou', 'fd'], false),
  EmojiFace('42', '爱情', ['aiqing', 'aq'], false),
  EmojiFace('43', '跳跳', ['tiaotiao', 'tt'], false),
  EmojiFace('46', '猪头', ['zhutou', 'zt'], false),
  EmojiFace('49', '拥抱', ['yongbao', 'yb'], false),
  EmojiFace('53', '蛋糕', ['dangao', 'dg'], false),
  EmojiFace('54', '闪电', ['shandian', 'sd'], false),
  EmojiFace('55', '炸弹', ['zhadan', 'zd'], false),
  EmojiFace('56', '刀', ['dao'], false),
  EmojiFace('57', '足球', ['zuqiu', 'zq'], false),
  EmojiFace('59', '便便', ['bianbian', 'bb'], false),
  EmojiFace('60', '咖啡', ['kafei', 'kf'], false),
  EmojiFace('61', '饭', ['fan'], false),
  EmojiFace('63', '玫瑰', ['meigui', 'mg'], false),
  EmojiFace('64', '凋谢', ['diaoxie', 'dx'], false),
  EmojiFace('66', '爱心', ['aixin', 'ax'], false),
  EmojiFace('67', '心碎', ['xinsui', 'xs'], false),
  EmojiFace('69', '礼物', ['liwu', 'lw'], false),
  EmojiFace('74', '太阳', ['taiyang', 'ty'], false),
  EmojiFace('75', '月亮', ['yueliang', 'yl'], false),
  EmojiFace('76', '赞', ['zan'], false),
  EmojiFace('77', '踩', ['cai'], false),
  EmojiFace('78', '握手', ['woshou', 'ws'], false),
  EmojiFace('79', '胜利', ['shengli', 'sl'], false),
  EmojiFace('85', '飞吻', ['feiwen', 'fw'], false),
  EmojiFace('86', '怄火', ['ouhuo', 'oh'], false),
  EmojiFace('89', '西瓜', ['xigua', 'xg'], false),
  EmojiFace('96', '冷汗', ['lenghan', 'lh'], false),
  EmojiFace('97', '擦汗', ['cahan', 'ch'], false),
  EmojiFace('98', '抠鼻', ['koubi', 'kb'], false),
  EmojiFace('99', '鼓掌', ['guzhang', 'gz'], false),
  EmojiFace('100', '糗大了', ['qiudale', 'qdl'], false),
  EmojiFace('101', '坏笑', ['huaixiao', 'hx'], false),
  EmojiFace('102', '左哼哼', ['zuohengheng', 'zhh'], false),
  EmojiFace('103', '右哼哼', ['youhengheng', 'yhh'], false),
  EmojiFace('104', '哈欠', ['haqian', 'hq'], false),
  EmojiFace('105', '鄙视', ['bishi', 'bs'], false),
  EmojiFace('106', '委屈', ['weiqu', 'wq'], false),
  EmojiFace('107', '快哭了', ['kuaikule', 'kkl'], false),
  EmojiFace('108', '阴险', ['yinxian', 'yx'], false),
  EmojiFace('109', '左亲亲', ['zuoqinqin', 'zqq'], false),
  EmojiFace('110', '吓', ['xia'], false),
  EmojiFace('111', '可怜', ['kelian', 'kl'], false),
  EmojiFace('112', '菜刀', ['caidao', 'cd'], false),
  EmojiFace('113', '啤酒', ['pijiu', 'pj'], false),
  EmojiFace('114', '篮球', ['lanqiu', 'lq'], false),
  EmojiFace('115', '乒乓', ['pingpang', 'pp'], false),
  EmojiFace('116', '示爱', ['shiai', 'sa'], false),
  EmojiFace('117', '瓢虫', ['piaochong', 'pc'], false),
  EmojiFace('118', '抱拳', ['baoquan', 'bq'], false),
  EmojiFace('119', '勾引', ['gouyin', 'gy'], false),
  EmojiFace('120', '拳头', ['quantou', 'qt'], false),
  EmojiFace('121', '差劲', ['chajin', 'cj'], false),
  EmojiFace('122', '爱你', ['aini', 'an'], false),
  EmojiFace('123', 'NO', ['NO', 'N'], false),
  EmojiFace('124', 'OK', ['OK', 'O'], false),
  EmojiFace('125', '转圈', ['zhuanquan', 'zq'], false),
  EmojiFace('126', '磕头', ['ketou', 'kt'], false),
  EmojiFace('127', '回头', ['huitou', 'ht'], false),
  EmojiFace('128', '跳绳', ['tiaosheng', 'ts'], false),
  EmojiFace('129', '挥手', ['huishou', 'hs'], false),
  EmojiFace('130', '激动', ['jidong', 'jd'], false),
  EmojiFace('131', '街舞', ['jiewu', 'jw'], false),
  EmojiFace('132', '献吻', ['xianwen', 'xw'], false),
  EmojiFace('133', '左太极', ['zuotaiji', 'ztj'], false),
  EmojiFace('134', '右太极', ['youtaiji', 'ytj'], false),
  EmojiFace('136', '双喜', ['shuangxi', 'sx'], false),
  EmojiFace('137', '鞭炮', ['bianpao', 'bp'], false),
  EmojiFace('138', '灯笼', ['denglong', 'dl'], false),
  EmojiFace('140', 'K歌', ['Kge', 'Kg'], false),
  EmojiFace('144', '喝彩', ['hecai', 'hc'], false),
  EmojiFace('145', '祈祷', ['qidao', 'qd'], false),
  EmojiFace('146', '爆筋', ['baojin', 'bj'], false),
  EmojiFace('147', '棒棒糖', ['bangbangtang', 'bbt'], false),
  EmojiFace('148', '喝奶', ['henai', 'hn'], false),
  EmojiFace('151', '飞机', ['feiji', 'fj'], false),
  EmojiFace('158', '钞票', ['chaopiao', 'cp'], false),
  EmojiFace('168', '药', ['yao'], false),
  EmojiFace('169', '手枪', ['shouqiang', 'sq'], false),
  EmojiFace('171', '茶', ['cha'], false),
  EmojiFace('172', '眨眼睛', ['zhayanjing', 'zyj'], false),
  EmojiFace('173', '泪奔', ['leiben', 'lb'], false),
  EmojiFace('174', '无奈', ['wunai', 'wn'], false),
  EmojiFace('175', '卖萌', ['maimeng', 'mm'], false),
  EmojiFace('176', '小纠结', ['xiaojiujie', 'xjj'], false),
  EmojiFace('177', '喷血', ['penxie', 'px'], false),
  EmojiFace('178', '斜眼笑', ['xieyanxiao', 'xyx'], false),
  EmojiFace('179', 'doge', ['doge', 'd'], false),
  EmojiFace('180', '惊喜', ['jingxi', 'jx'], false),
  EmojiFace('181', '骚扰', ['saorao', 'sr'], false),
  EmojiFace('182', '笑哭', ['xiaoku', 'xk'], false),
  EmojiFace('183', '我最美', ['wozuimei', 'wzm'], false),
  EmojiFace('184', '河蟹', ['hexie', 'hx'], false),
  EmojiFace('185', '羊驼', ['yangtuo', 'yt'], false),
  EmojiFace('187', '幽灵', ['youling', 'yl'], false),
  EmojiFace('188', '蛋', ['dan'], false),
  EmojiFace('190', '菊花', ['juhua', 'jh'], false),
  EmojiFace('192', '红包', ['hongbao', 'hb'], false),
  EmojiFace('193', '大笑', ['daxiao', 'dx'], false),
  EmojiFace('194', '不开心', ['bukaixin', 'bkx'], false),
  EmojiFace('197', '冷漠', ['lengmo', 'lm'], false),
  EmojiFace('198', '呃', ['e'], false),
  EmojiFace('199', '好棒', ['haobang', 'hb'], false),
  EmojiFace('200', '拜托', ['baituo', 'bt'], false),
  EmojiFace('201', '点赞', ['dianzan', 'dz'], false),
  EmojiFace('202', '无聊', ['wuliao', 'wl'], false),
  EmojiFace('203', '托脸', ['tuolian', 'tl'], false),
  EmojiFace('204', '吃', ['chi'], false),
  EmojiFace('205', '送花', ['songhua', 'sh'], false),
  EmojiFace('206', '害怕', ['haipa', 'hp'], false),
  EmojiFace('207', '花痴', ['huachi', 'hc'], false),
  EmojiFace('208', '小样儿', ['xiaoyanger', 'xye'], false),
  EmojiFace('210', '飙泪', ['biaolei', 'bl'], false),
  EmojiFace('211', '我不看', ['wobukan', 'wbk'], false),
  EmojiFace('212', '托腮', ['tuosai', 'ts'], false),
  EmojiFace('214', '啵啵', ['bobo', 'bb'], false),
  EmojiFace('215', '糊脸', ['hulian', 'hl'], false),
  EmojiFace('216', '拍头', ['paitou', 'pt'], false),
  EmojiFace('217', '扯一扯', ['cheyiche', 'cyc'], false),
  EmojiFace('218', '舔一舔', ['tianyitian', 'tyt'], false),
  EmojiFace('219', '蹭一蹭', ['cengyiceng', 'cyc'], false),
  EmojiFace('220', '拽炸天', ['zhuaizhatian', 'zzt'], false),
  EmojiFace('221', '顶呱呱', ['dingguagua', 'dgg'], false),
  EmojiFace('222', '抱抱', ['baobao', 'bb'], false),
  EmojiFace('223', '暴击', ['baoji', 'bj'], false),
  EmojiFace('224', '开枪', ['kaiqiang', 'kq'], false),
  EmojiFace('225', '撩一撩', ['liaoyiliao', 'lyl'], false),
  EmojiFace('226', '拍桌', ['paizhuo', 'pz'], false),
  EmojiFace('227', '拍手', ['paishou', 'ps'], false),
  EmojiFace('228', '恭喜', ['gongxi', 'gx'], false),
  EmojiFace('229', '干杯', ['ganbei', 'gb'], false),
  EmojiFace('230', '嘲讽', ['chaofeng', 'cf'], false),
  EmojiFace('231', '哼', ['heng'], false),
  EmojiFace('232', '佛系', ['foxi', 'fx'], false),
  EmojiFace('233', '掐一掐', ['qiayiqia', 'qyq'], false),
  EmojiFace('234', '惊呆', ['jingdai', 'jd'], false),
  EmojiFace('235', '颤抖', ['chandou', 'cd'], false),
  EmojiFace('236', '啃头', ['kentou', 'kt'], false),
  EmojiFace('237', '偷看', ['toukan', 'tk'], false),
  EmojiFace('238', '扇脸', ['shanlian', 'sl'], false),
  EmojiFace('239', '原谅', ['yuanliang', 'yl'], false),
  EmojiFace('240', '喷脸', ['penlian', 'pl'], false),
  EmojiFace('241', '生日快乐', ['shengrikuaile', 'srkl'], false),
  EmojiFace('242', '头撞击', ['touzhuangji', 'tzj'], false),
  EmojiFace('243', '甩头', ['shuaitou', 'st'], false),
  EmojiFace('244', '扔狗', ['renggou', 'rg'], false),
  EmojiFace('245', '加油必胜', ['jiayoubisheng', 'jybs'], false),
  EmojiFace('246', '加油抱抱', ['jiayoubaobao', 'jybb'], false),
  EmojiFace('247', '口罩护体', ['kouzhaohuti', 'kzht'], false),
  EmojiFace('260', '搬砖中', ['banzhuanzhong', 'bzz'], false),
  EmojiFace('261', '忙到飞起', ['mangdaofeiqi', 'mdfq'], false),
  EmojiFace('262', '脑阔疼', ['naokuoteng', 'nkt'], false),
  EmojiFace('263', '沧桑', ['cangsang', 'cs'], false),
  EmojiFace('264', '捂脸', ['wulian', 'wl'], false),
  EmojiFace('265', '辣眼睛', ['layanjing', 'lyj'], false),
  EmojiFace('266', '哦哟', ['oyo', 'oy'], false),
  EmojiFace('267', '头秃', ['toutu', 'tt'], false),
  EmojiFace('268', '问号脸', ['wenhaolian', 'whl'], false),
  EmojiFace('269', '暗中观察', ['anzhongguancha', 'azgc'], false),
  EmojiFace('270', 'emm', ['emm', 'e'], false),
  EmojiFace('271', '吃瓜', ['chigua', 'cg'], false),
  EmojiFace('272', '呵呵哒', ['heheda', 'hhd'], false),
  EmojiFace('273', '我酸了', ['wosuanle', 'wsl'], false),
  EmojiFace('274', '太南了', ['tainanle', 'tnl'], false),
  EmojiFace('276', '辣椒酱', ['lajiaojiang', 'ljj'], false),
  EmojiFace('277', '汪汪', ['wangwang', 'ww'], false),
  EmojiFace('278', '汗', ['han'], false),
  EmojiFace('279', '打脸', ['dalian', 'dl'], false),
  EmojiFace('280', '击掌', ['jizhang', 'jz'], false),
  EmojiFace('281', '无眼笑', ['wuyanxiao', 'wyx'], false),
  EmojiFace('282', '敬礼', ['jingli', 'jl'], false),
  EmojiFace('283', '狂笑', ['kuangxiao', 'kx'], false),
  EmojiFace('284', '面无表情', ['mianwubiaoqing', 'mwbq'], false),
  EmojiFace('285', '摸鱼', ['moyu', 'my'], false),
  EmojiFace('286', '魔鬼笑', ['moguixiao', 'mgx'], false),
  EmojiFace('287', '哦', ['o'], false),
  EmojiFace('288', '请', ['qing'], false),
  EmojiFace('289', '睁眼', ['zhengyan', 'zy'], false),
  EmojiFace('290', '敲开心', ['qiaokaixin', 'qkx'], false),
  EmojiFace('291', '震惊', ['zhenjing', 'zj'], false),
  EmojiFace('292', '让我康康', ['rangwokangkang', 'rwkk'], false),
  EmojiFace('293', '摸锦鲤', ['mojinli', 'mjl'], false),
  EmojiFace('294', '期待', ['qidai', 'qd'], false),
  EmojiFace('295', '拿到红包', ['nadaohongbao', 'ndhb'], false),
  EmojiFace('296', '真好', ['zhenhao', 'zh'], false),
  EmojiFace('297', '拜谢', ['baixie', 'bx'], false),
  EmojiFace('298', '元宝', ['yuanbao', 'yb'], false),
  EmojiFace('299', '牛啊', ['niua', 'na'], false),
  EmojiFace('300', '胖三斤', ['pangsanjin', 'psj'], false),
  EmojiFace('301', '好闪', ['haoshan', 'hs'], false),
  EmojiFace('302', '左拜年', ['zuobainian', 'zbn'], false),
  EmojiFace('303', '右拜年', ['youbainian', 'ybn'], false),
  EmojiFace('304', '红包包', ['hongbaobao', 'hbb'], false),
  EmojiFace('305', '右亲亲', ['youqinqin', 'yqq'], false),
  EmojiFace('306', '牛气冲天', ['niuqichongtian', 'nqct'], false),
  EmojiFace('307', '喵喵', ['miaomiao', 'mm'], false),
  EmojiFace('308', '求红包', ['qiuhongbao', 'qhb'], false),
  EmojiFace('309', '谢红包', ['xiehongbao', 'xhb'], false),
  EmojiFace('310', '新年烟花', ['xinnianyanhua', 'xnyh'], false),
  EmojiFace('311', '打call', ['dacall', 'dc'], false),
  EmojiFace('312', '变形', ['bianxing', 'bx'], false),
  EmojiFace('313', '嗑到了', ['kedaole', 'kdl'], false),
  EmojiFace('314', '仔细分析', ['zixifenxi', 'zxfx'], false),
  EmojiFace('315', '加油', ['jiayou', 'jy'], false),
  EmojiFace('316', '我没事', ['womeishi', 'wms'], false),
  EmojiFace('317', '菜狗', ['caigou', 'cg'], false),
  EmojiFace('318', '崇拜', ['chongbai', 'cb'], false),
  EmojiFace('319', '比心', ['bixin', 'bx'], false),
  EmojiFace('320', '庆祝', ['qingzhu', 'qz'], false),
  EmojiFace('321', '老色痞', ['laosepi', 'lsp'], false),
  EmojiFace('322', '拒绝', ['jujue', 'jj'], false),
  EmojiFace('323', '嫌弃', ['xianqi', 'xq'], false),
  EmojiFace('324', '吃糖', [], false),
  EmojiFace('325', '惊吓', [], false),
  EmojiFace('326', '生气', [], false),
  EmojiFace('327', '加一', [], false),
  EmojiFace('328', '错号', [], false),
  EmojiFace('329', '对号', [], false),
  EmojiFace('330', '完成', [], false),
  EmojiFace('331', '明白', [], false),
  EmojiFace('332', '举牌牌', [], false),
  EmojiFace('333', '烟花', [], false),
  EmojiFace('334', '虎虎生威', [], false),
  EmojiFace('336', '豹富', [], false),
  EmojiFace('337', '花朵脸', [], false),
  EmojiFace('338', '我想开了', [], false),
  EmojiFace('339', '舔屏', [], false),
  EmojiFace('340', '热化了', [], false),
  EmojiFace('341', '打招呼', [], false),
  EmojiFace('342', '酸Q', [], false),
  EmojiFace('343', '我方了', [], false),
  EmojiFace('344', '大怨种', [], false),
  EmojiFace('345', '红包多多', [], false),
  EmojiFace('346', '你真棒棒', [], false),
  EmojiFace('347', '大展宏兔', [], false),
  EmojiFace('348', '福萝卜', [], false),
  EmojiFace('364', '超级赞', [], true),
  EmojiFace('366', '芒狗', [], true),
  EmojiFace('362', '好兄弟', [], true),
  EmojiFace('397', '抛媚眼', [], true),
  EmojiFace('396', '狼狗', [], true),
  EmojiFace('360', '亲亲', [], true),
  EmojiFace('361', '狗狗笑哭', [], true),
  EmojiFace('363', '狗狗可怜', [], true),
  EmojiFace('365', '狗狗生气', [], true),
  EmojiFace('367', '狗狗疑问', [], true),
  EmojiFace('413', '摇起来', [], true),
  EmojiFace('405', '好运来', [], true),
  EmojiFace('404', '闪亮登场', [], true),
  EmojiFace('406', '姐是女王', [], true),
  EmojiFace('410', '么么哒', [], true),
  EmojiFace('411', '一起嗨', [], true),
  EmojiFace('407', '我听听', [], true),
  EmojiFace('408', '臭美', [], true),
  EmojiFace('412', '开心', [], true),
  EmojiFace('409', '送你花花', [], true),
  EmojiFace('403', '出去玩', [], true),
  EmojiFace('402', '别说话', [], true),
  EmojiFace('390', '太头秃', [], true),
  EmojiFace('391', '太沧桑', [], true),
  EmojiFace('388', '太头疼', [], true),
  EmojiFace('389', '太赞了', [], true),
  EmojiFace('386', '呜呜呜', [], true),
  EmojiFace('385', '太气了', [], true),
  EmojiFace('384', '晚安', [], true),
  EmojiFace('387', '太好笑', [], true),
  EmojiFace('382', 'emo', [], true),
  EmojiFace('383', '企鹅爱心', [], true),
  EmojiFace('401', '超级转圈', [], true),
  EmojiFace('400', '快乐', [], true),
  EmojiFace('380', '真棒', [], true),
  EmojiFace('381', '路过', [], true),
  EmojiFace('379', '企鹅流泪', [], true),
  EmojiFace('376', '跺脚', [], true),
  EmojiFace('378', '企鹅笑哭', [], true),
  EmojiFace('377', '嗨', [], true),
  EmojiFace('399', 'tui', [], true),
  EmojiFace('398', '超级ok', [], true),
  EmojiFace('373', '忙', [], true),
  EmojiFace('370', '祝贺', [], true),
  EmojiFace('375', '超级鼓掌', [], true),
  EmojiFace('368', '奥特笑哭', [], true),
  EmojiFace('369', '彩虹', [], true),
  EmojiFace('371', '冒泡', [], true),
  EmojiFace('372', '气呼呼', [], true),
  EmojiFace('374', '波波流泪', [], true),
];

final _faceByName = <String, EmojiFace>{
  for (final face in emojiFaces) face.name: face,
};

/// token 形状：`[/名字]`。只认方括号里没有嵌套括号的短名字。
final _tokenPattern = RegExp(r'\[/([^\[\]]{1,24})\]');

final _faceById = <String, EmojiFace>{
  for (final face in emojiFaces) face.id: face,
};

EmojiFace? emojiFaceByName(String name) => _faceByName[name];

EmojiFace? emojiFaceById(String id) => _faceById[id];

bool hasEmojiToken(String text) => _tokenPattern.hasMatch(text);

/// 把正文切成「纯文本 + 表情图」交替的 spans。
/// 只有名字能在总表里查到的 token 才变成图片，正文里恰好写成方括号的内容不会被误伤。
List<InlineSpan> emojiSpans(String text, {TextStyle? style, double size = 20}) {
  final spans = <InlineSpan>[];
  var cursor = 0;
  for (final match in _tokenPattern.allMatches(text)) {
    final face = _faceByName[match.group(1)];
    if (face == null) continue;
    if (match.start > cursor) {
      spans.add(TextSpan(text: text.substring(cursor, match.start), style: style));
    }
    spans.add(
      WidgetSpan(
        alignment: PlaceholderAlignment.middle,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 1),
          child: Image.asset(
            face.asset,
            width: size,
            height: size,
            filterQuality: FilterQuality.medium,
          ),
        ),
      ),
    );
    cursor = match.end;
  }
  if (cursor == 0) return [TextSpan(text: text, style: style)];
  if (cursor < text.length) {
    spans.add(TextSpan(text: text.substring(cursor), style: style));
  }
  return spans;
}

/// 输入框控制器：把 `[/名字]` 画成内联表情图，内部仍然只保存纯文本 token，
/// 因此草稿、发送、长度限制与服务端校验都与普通文本完全一致。
class EmojiEditingController extends TextEditingController {
  EmojiEditingController({super.text});

  /// 在光标处插入表情；没有有效选区时追加到末尾。
  void insertFace(EmojiFace face) {
    final token = face.token;
    final selection = this.selection;
    final start = selection.isValid ? selection.start : text.length;
    final end = selection.isValid ? selection.end : text.length;
    value = TextEditingValue(
      text: text.replaceRange(start, end, token),
      selection: TextSelection.collapsed(offset: start + token.length),
    );
  }

  @override
  TextSpan buildTextSpan({
    required BuildContext context,
    TextStyle? style,
    required bool withComposing,
  }) {
    // 中文输入法组词期间一律退回纯文本：合成区间的下划线不能与表情图混排，
    // 否则拼音候选阶段的光标与候选框会错位。组词结束后表情自然显示出来。
    if (!withComposing && hasEmojiToken(text)) {
      return TextSpan(style: style, children: emojiSpans(text, style: style));
    }
    return super.buildTextSpan(
      context: context,
      style: style,
      withComposing: withComposing,
    );
  }
}
