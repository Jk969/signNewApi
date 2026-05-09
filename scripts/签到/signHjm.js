const axios = require('axios');
const fs = require('fs');
const path = require('path');

const API_BASE = 'https://api.gemai.cc';
const CACHE_FILE = path.join(__dirname, '.gemai_cache.json');

const USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36 Edg/145.0.0.0';

function loadCache() {
  try {
    if (fs.existsSync(CACHE_FILE)) {
      const data = fs.readFileSync(CACHE_FILE, 'utf8');
      return JSON.parse(data);
    }
  } catch (e) {
    console.log('缓存读取失败:', e.message);
  }
  return {};
}

function saveCache(cache) {
  try {
    fs.writeFileSync(CACHE_FILE, JSON.stringify(cache, null, 2));
  } catch (e) {
    console.log('缓存保存失败:', e.message);
  }
}

async function getAccounts() {
  const accounts = [];
  
  if (typeof QLAPI !== 'undefined' && QLAPI.getEnvs) {
    try {
      const result = await QLAPI.getEnvs({ searchValue: 'GEMAI_ACCOUNT' });
      if (result.code === 200 && result.data) {
        for (const env of result.data) {
          if (env.name === 'GEMAI_ACCOUNT' && env.value && env.remarks) {
            accounts.push({
              username: env.value.trim(),
              password: env.remarks.trim(),
              remark: env.value.trim()
            });
          }
        }
      }
    } catch (e) {
      console.log('QLAPI 获取失败，使用 process.env:', e.message);
    }
  }
  
  if (accounts.length === 0) {
    const envValue = process.env.GEMAI_ACCOUNT;
    if (envValue) {
      let values = envValue;
      if (Array.isArray(values)) {
        values.forEach(item => {
          const line = item.toString().trim();
          if (line) processAccountLine(line, accounts);
        });
      } else {
        const lines = values.toString().split(/[\n&]/).map(l => l.trim()).filter(l => l);
        lines.forEach(line => processAccountLine(line, accounts));
      }
    }
  }
  
  return accounts;
}

function processAccountLine(line, accounts) {
  const parts = line.split('###');
  const username = parts[0].trim();
  const password = parts[1]?.trim() || '';
  const remark = parts[2]?.trim() || username;
  if (username && password) {
    accounts.push({ username, password, remark });
  }
}

async function login(username, password) {
  try {
    const response = await axios.post(
      `${API_BASE}/api/user/login?turnstile=`,
      { username, password },
      {
        headers: {
          'accept': 'application/json, text/plain, */*',
          'accept-language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
          'cache-control': 'no-store',
          'content-type': 'application/json',
          'origin': 'https://api.gemai.cc',
          'priority': 'u=1, i',
          'referer': 'https://api.gemai.cc/login',
          'sec-ch-ua': '"Not:A-Brand";v="99", "Microsoft Edge";v="145", "Chromium";v="145"',
          'sec-ch-ua-mobile': '?0',
          'sec-ch-ua-platform': '"Windows"',
          'sec-fetch-dest': 'empty',
          'sec-fetch-mode': 'cors',
          'sec-fetch-site': 'same-origin',
          'user-agent': USER_AGENT
        }
      }
    );
    
    if (response.data.success) {
      const setCookie = response.headers['set-cookie'];
      let session = '';
      if (setCookie && setCookie.length > 0) {
        const match = setCookie[0].match(/session=([^;]+)/);
        if (match) session = match[1];
      }
      
      const userId = response.data.data.id;
      return {
        success: true,
        session,
        userId,
        username: response.data.data.username
      };
    }
    return { success: false, message: response.data.message };
  } catch (error) {
    return { success: false, message: error.response?.data?.message || error.message };
  }
}

async function getValidCookie(account, cache) {
  const cacheKey = account.username;
  const cached = cache[cacheKey];
  
  if (cached && cached.session && cached.userId) {
    const testCookie = `session=${cached.session}; new-api-user=${cached.userId}`;
    const isValid = await testCookieValid(testCookie);
    if (isValid) {
      console.log(`使用缓存的Cookie: ${account.remark}`);
      return { cookie: testCookie, userId: cached.userId, fromCache: true };
    }
    console.log(`Cookie已失效，重新登录: ${account.remark}`);
  }
  
  console.log(`登录获取Cookie: ${account.remark}`);
  const loginResult = await login(account.username, account.password);
  
  if (!loginResult.success) {
    return { error: loginResult.message };
  }
  
  cache[cacheKey] = {
    session: loginResult.session,
    userId: loginResult.userId,
    username: loginResult.username,
    updatedAt: new Date().toISOString()
  };
  saveCache(cache);
  
  const cookie = `session=${loginResult.session}; new-api-user=${loginResult.userId}`;
  return { cookie, userId: loginResult.userId, fromCache: false };
}

async function testCookieValid(cookie) {
  try {
    const currentMonth = new Date().toISOString().slice(0, 7);
    const response = await axios.get(
      `${API_BASE}/api/user/checkin?month=${currentMonth}`,
      {
        headers: getHeaders(cookie),
        timeout: 10000
      }
    );
    return response.data.success === true;
  } catch (error) {
    return false;
  }
}

function getHeaders(cookie) {
  const match = cookie.match(/new-api-user[=:]([^;&\s]+)/i);
  const userId = match ? match[1] : '';
  return {
    'accept': 'application/json, text/plain, */*',
    'accept-language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
    'cache-control': 'no-store',
    'cookie': cookie,
    'new-api-user': userId,
    'priority': 'u=1, i',
    'referer': 'https://api.gemai.cc/console/personal',
    'sec-ch-ua': '"Not:A-Brand";v="99", "Microsoft Edge";v="145", "Chromium";v="145"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Windows"',
    'sec-fetch-dest': 'empty',
    'sec-fetch-mode': 'cors',
    'sec-fetch-site': 'same-origin',
    'user-agent': USER_AGENT
  };
}

async function checkCheckinStatus(cookie) {
  const currentMonth = new Date().toISOString().slice(0, 7);
  try {
    const response = await axios.get(
      `${API_BASE}/api/user/checkin?month=${currentMonth}`,
      { headers: getHeaders(cookie) }
    );
    return response.data;
  } catch (error) {
    console.error('查询签到状态失败:', error.message);
    return null;
  }
}

async function doCheckin(cookie) {
  try {
    const response = await axios.post(
      `${API_BASE}/api/user/checkin`,
      {},
      {
        headers: {
          ...getHeaders(cookie),
          'content-length': '0',
          'origin': 'https://api.gemai.cc'
        }
      }
    );
    return response.data;
  } catch (error) {
    if (error.response?.data) {
      return error.response.data;
    }
    console.error('签到请求失败:', error.message);
    return null;
  }
}

async function sendPushPlus(title, content) {
  const token = process.env.PUSH_PLUS_TOKEN || process.env.PUSHPLUS_TOKEN;
  if (!token) {
    console.log('未配置 PushPlus Token，跳过推送');
    return;
  }
  
  try {
    const response = await axios.post('https://www.pushplus.plus/send', {
      token: token,
      title: title,
      content: content,
      template: 'txt'
    });
    
    if (response.data.code === 200) {
      console.log('PushPlus 推送成功');
    } else {
      console.log('PushPlus 推送失败:', response.data.msg);
    }
  } catch (error) {
    console.error('PushPlus 推送错误:', error.message);
  }
}

async function main() {
  console.log('========== GemAI 签到脚本开始 ==========\n');
  
  const accounts = await getAccounts();
  
  if (accounts.length === 0) {
    console.log('没有找到有效的账号');
    console.log('请设置环境变量 GEMAI_ACCOUNT');
    console.log('格式: 用户名###密码###备注');
    console.log('多账号用 & 或换行分隔');
    await sendPushPlus('GemAI签到-失败', '未找到有效的账号配置');
    return;
  }
  
  console.log(`检测到 ${accounts.length} 个账号\n`);
  
  const cache = loadCache();
  let successCount = 0;
  let alreadyCount = 0;
  let failCount = 0;
  const details = [];
  
  for (let i = 0; i < accounts.length; i++) {
    const account = accounts[i];
    console.log(`--- 账号 ${i + 1}: ${account.remark} ---`);
    
    const auth = await getValidCookie(account, cache);
    if (auth.error) {
      console.log(`❌ 登录失败: ${auth.error}\n`);
      details.push(`【${account.remark}】❌ 登录失败\n原因: ${auth.error}`);
      failCount++;
      continue;
    }
    
    if (auth.fromCache) {
      console.log('使用缓存Cookie');
    } else {
      console.log('登录成功，已缓存Cookie');
    }
    
    const statusData = await checkCheckinStatus(auth.cookie);
    
    if (statusData?.data?.stats?.checked_in_today) {
      console.log('今日已签到');
      console.log(`累计签到: ${statusData.data.stats.total_checkins} 次`);
      console.log(`总配额: ${(statusData.data.stats.total_quota / 10000000).toFixed(1)}000万\n`);
      details.push(`【${account.remark}】今日已签到\n累计签到: ${statusData.data.stats.total_checkins} 次\n总配额: ${(statusData.data.stats.total_quota / 10000000).toFixed(1)}000万`);
      alreadyCount++;
      continue;
    }
    
    const checkinResult = await doCheckin(auth.cookie);
    
    if (checkinResult?.success) {
      console.log(`✅ 签到成功!`);
      console.log(`签到日期: ${checkinResult.data.checkin_date}`);
      console.log(`获得配额: ${(checkinResult.data.quota_awarded / 10000000).toFixed(1)}000万\n`);
      details.push(`【${account.remark}】✅ 签到成功\n签到日期: ${checkinResult.data.checkin_date}\n获得配额: ${(checkinResult.data.quota_awarded / 10000000).toFixed(1)}000万`);
      successCount++;
    } else if (checkinResult?.message === '今日已签到') {
      console.log('今日已签到\n');
      details.push(`【${account.remark}】今日已签到`);
      alreadyCount++;
    } else {
      console.log(`❌ 签到失败: ${checkinResult?.message || '未知错误'}\n`);
      details.push(`【${account.remark}】❌ 签到失败\n原因: ${checkinResult?.message || '未知错误'}`);
      failCount++;
    }
  }
  
  console.log('========== 签到完成 ==========');
  console.log(`成功: ${successCount}, 已签到: ${alreadyCount}, 失败: ${failCount}`);
  
  const now = new Date().toLocaleString('zh-CN');
  const total = accounts.length;
  const statusEmoji = failCount > 0 ? '❌' : (successCount > 0 ? '✅' : '✓');
  const title = `${statusEmoji} GemAI签到 ${successCount}成功 ${alreadyCount}已签 ${failCount}失败`;
  
  const content = `⏰ 执行时间: ${now}
📊 统计: 共${total}个账号 | 成功${successCount} | 已签${alreadyCount} | 失败${failCount}

${details.join('\n\n')}`;
  
  await sendPushPlus(title, content);
}

main().catch(console.error);
