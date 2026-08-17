(function () {
  'use strict';

  const assetFormat = (mime) => ({
    'image/svg+xml': 'svg',
    'image/png': 'png',
    'image/jpeg': 'jpeg',
    'image/gif': 'gif',
    'image/webp': 'webp',
    'image/bmp': 'bmp',
    'image/x-icon': 'ico',
    'image/vnd.microsoft.icon': 'ico',
  }[mime] || '');

  // 밈트폴리오 종목 검색 전용 로고 카탈로그입니다. 각 자산은 공식 회사
  // 페이지가 직접 선언한 URL만 회사 홈페이지 resolver와 동일한 검증기로
  // 확인했습니다. 라이브 publication의 기업 로고 계약과는 별도 범위입니다.
  const verifiedMakerLogo = (
    sourcePageUrl, assetUrl, mime, width, height, sha256,
    candidateKind = 'reviewed_official_asset', assetScope = 'same_official_domain', displayMode = 'contain'
  ) => {
    const format = assetFormat(mime);
    const verification = format === 'svg'
      ? 'verified_safe_svg'
      : (width >= 64 && height >= 64 ? 'verified_raster_min_64px' : 'verified_raster_wordmark');
    return Object.freeze({
      logo_url: assetUrl,
      logo_render_mode: 'image',
      logo_asset_scope: 'maker_stock_search',
      logo_asset_source: 'official_page_asset',
      logo_asset_verification: verification,
      logo_asset_format: format,
      logo_asset_mime: mime,
      logo_asset_width: width,
      logo_asset_height: height,
      logo_asset_sha256: sha256,
      logo_source_page_url: sourcePageUrl,
      logo_runtime_probe_required: false,
      logo_display_mode: displayMode,
      logo_minimum_dimension: 64,
      logo_provenance: Object.freeze({
        source_page_url: sourcePageUrl,
        asset_url: assetUrl,
        mime, width, height, sha256, verification,
        candidate_kind: candidateKind,
        asset_scope: assetScope,
      }),
    });
  };

  const verifiedMakerLogos = Object.freeze({
    'samsung.com': verifiedMakerLogo(
      'https://www.samsung.com/global/ir/',
      'https://resources.samsung.com/etc.clientlibs/samsung/clientlibs/consumer/global/clientlib-common/resources/images/app_ico.png',
      'image/png', 144, 144, '466bfa1802115d9a8ef53ab62278f0df859b9f4586a2bddb0e3d1f5e5da0eca2', 'apple_touch_icon', 'same_official_domain'
    ),
    'skhynix.com': verifiedMakerLogo(
      'https://www.skhynix.com/company/UI-FR-CP0402/',
      'https://mis-prod-koce-skhynixhomepage-cdn-01-ep.azureedge.net/img/content/img_ci02.png',
      'image/png', 600, 296, '9bc5a835505735ca15c8692b126838e7ac758ed151badb5703a71a2dfa92450b', 'reviewed_ci_image', 'official_page_declared_cdn'
    ),
    'navercorp.com': verifiedMakerLogo(
      'https://navercorp.com/main', 'https://navercorp.com/img/favicon.ico',
      'image/x-icon', 256, 256, 'cddaaa35e5464c57990c0674cca6e331c2a492ce7a7ed8f7ac1105da76709ecf', 'icon'
    ),
    'kakaocorp.com': verifiedMakerLogo(
      'https://www.kakaocorp.com/page/', 'https://t1.kakaocdn.net/kakaocorp/corp_thumbnail/Kakao.png',
      'image/png', 800, 800, '63ad018488cf671e4e74d26ec24c0ef7990ac23605bdbbd953ac33df4b7e48ce', 'og_image', 'official_page_declared_cdn'
    ),
    'hyundai.com': verifiedMakerLogo(
      'https://www.hyundai.com/kr/ko/info/ci',
      'https://www.hyundai.com/content/dam/hyundai/kr/ko/images/common/h1-logo.png',
      'image/png', 149, 70, '7a0bd59877fb713881f7e95c7b8cbb0757d4432b8b6cf7c2d1942c2e02eaffc0', 'reviewed_ci_image'
    ),
    'kia.com': verifiedMakerLogo(
      'https://www.kia.com/kr',
      'https://www.kia.com/etc.clientlibs/kwp-global/clientlibs/clientlib-site/resources/images/common/logo.svg',
      'image/svg+xml', 103, 51, '584cde1a743691da9dbd07ddd1277613b9041f7bf6711026ac69b03dc65f441f', 'reviewed_official_logo'
    ),
    'lgensol.com': verifiedMakerLogo(
      'https://www.lgensol.com/kr/index', 'https://www.lgensol.com/inc/images/img/img_footer_logo.svg',
      'image/svg+xml', 221, 23, 'c41d31d59a215ba30e85c49930e02c51e56c71b9b1ebcf2c393159019654f6f9', 'explicit_logo_image'
    ),
    'samsungbiologics.com': verifiedMakerLogo(
      'https://samsungbiologics.com/', 'https://samsungbiologics.com/resources/front/common/logo_sbl.png',
      'image/png', 500, 500, '7f3cf6a4408212bf7f029abf9539b8e6c86b187a4a2f3310a77baa8d6e4e1383', 'og_image'
    ),
    'celltrion.com': verifiedMakerLogo(
      'https://www.celltrion.com/en-us/company/celltrion/brand',
      'https://www.celltrion.com/front/assets/common/images/download/celltrion_CI.png',
      'image/png', 1200, 600, 'da79a8830b619fac6815e2c17c3c39c379647de81284c28f4091da77e8a68894', 'reviewed_ci_download'
    ),
    'posco-inc.com': verifiedMakerLogo(
      'https://posco-inc.com/hs91a1-front/app/index.html',
      'https://posco-inc.com/hs91a1-front/app/assets/img/favicon/favicon-180.png',
      'image/png', 180, 180, 'a8fab9dd54f6177df844c86bb33e6d22f9feb3b58ce73a4b6125dae11b4f70c8', 'apple_touch_icon'
    ),
    'kbfg.com': verifiedMakerLogo(
      'https://www.kbfg.com/eng/about/corporate/ci.htm',
      'https://www.kbfg.com/eng/images/about/mo/img_symbol_logo.jpg',
      'image/jpeg', 654, 192, 'a80624be962026e3fbf2806deddd359e1489bb4a146bde2db2379c803724784f', 'reviewed_ci_image'
    ),
    'shinhangroup.com': verifiedMakerLogo(
      'https://shinhangroup.com/kr/main',
      'https://shinhangroup.com/resources/publish/kr/images/common/favicon_144_144.png',
      'image/png', 144, 144, '019b9e9135a3ad3c876ba909dd9234ff3718655ea1a640f81dd40e985aafc9a4', 'apple_touch_icon'
    ),
    'kiwoom.com': verifiedMakerLogo(
      'https://www.kiwoom.com/h/customer/pamo/VPamoInfoView?PopXmitContent=Y',
      'https://www.kiwoom.com/h/kws/assets/images/customer/pamo/profile.png',
      'image/png', 68, 68, '1988173e8cfd4b47e7e7d8b394dd6b3bed4a5e2de277a9e126b519d577ebd9b7', 'reviewed_official_profile_mark'
    ),
    'lottewellfood.com': verifiedMakerLogo(
      'https://www.lottewellfood.com/', 'https://www.lottewellfood.com/images/common/m/h1_logo_new.png',
      'image/png', 206, 64, '8c0949e9f129e1f5375ca8d08846e3c29a4d1d55ad337ba1653a077d25bb7aca', 'explicit_logo_image'
    ),
    'hanwha.com': verifiedMakerLogo(
      'https://www.hanwha.com/', 'https://www.hanwha.com/assets/img/common/logo_black.svg',
      'image/svg+xml', 145, 40, '8b640a433cbe377e601cb6c59427b5703afa79b569ff58970f530a4818b8b2c7',
      'explicit_logo_image', 'same_official_domain', 'symbol_crop_left'
    ),
    'mrbluecorp.com': verifiedMakerLogo(
      'https://www.mrbluecorp.com/',
      'https://www.mrbluecorp.com/theme/basic/image/logo.png',
      'image/png', 94, 60, '61f25430b1971625fbe000e8ec767b929e76965e98d68fc2f94aeb817dd63bd4',
      'explicit_logo_image'
    ),
    'livsmed.com': verifiedMakerLogo(
      'https://www.livsmed.com/', 'https://www.livsmed.com/img/logo.png',
      'image/png', 306, 60, 'bc1c0f00dcab40d0879085b98783a999b5661e825e5ec75903182acf1167798d',
      'explicit_logo_image'
    ),
    'doosanrobotics.com': verifiedMakerLogo(
      'https://www.doosanrobotics.com/en/', 'https://www.doosanrobotics.com/images/logo.svg',
      'image/svg+xml', 127, 18, '407d6e38ebd40770bed7eb4c6839943ca5871fefaa0e08382688fa8142bc8ec8', 'explicit_logo_image'
    ),
    'apple.com': verifiedMakerLogo(
      'https://www.apple.com/newsroom/',
      'https://www.apple.com/newsroom/images/default/apple-logo-og.jpg?202608140503',
      'image/jpeg', 1200, 630, '2172fd3dbe2adb1180222673a64c2ab28f984e443cc11133bf774a33044ce391', 'og_image'
    ),
    // Microsoft remains an initials fallback: no redistributable official
    // asset that also passed the runtime availability check is pinned here.
    'abc.xyz': verifiedMakerLogo(
      'https://abc.xyz/', 'https://s206.q4cdn.com/479360582/files/design/alphabet_logo.png',
      'image/png', 800, 188, 'de61b1204d6ab077ebef10b5392523a8208dc0276278ce5a9bb5e4c891ef93d8', 'explicit_logo_image', 'official_page_declared_cdn'
    ),
    'about.meta.com': verifiedMakerLogo(
      'https://www.meta.com/ko-kr/about/?utm_source=about.meta.com&utm_medium=redirect',
      'https://static.xx.fbcdn.net/rsrc.php/yQ/r/0eWKxz9kEoF.webp',
      'image/webp', 180, 180, '2d1ac8a2fd4b90aa0e4be05bfdb634c02404c94c9f5c1923e4be7b89fa36cfe3', 'apple_touch_icon', 'official_page_declared_cdn'
    ),
    'amazon.com': verifiedMakerLogo(
      'https://www.aboutamazon.com/',
      'https://www.aboutamazon.com/_next/static/media/apple-touch-icon.706b1b87.png',
      'image/png', 180, 180, 'f8184c36ab5439a22007f105d0366f10bbb782ab1d379e38759e452965c18805', 'apple_touch_icon'
    ),
    'nvidia.com': verifiedMakerLogo(
      'https://www.nvidia.com/en-us/about-nvidia/',
      'https://www.nvidia.com/content/dam/en-zz/Solutions/about-nvidia/nvidia-brochure/images/nvidia-logo-black.svg',
      'image/svg+xml', 975, 180, 'b979e9c0240b9b45098cb7ce691124b97d774da3a68006ba046f29df0ce5d6db', 'reviewed_official_logo'
    ),
    'tesla.com': verifiedMakerLogo(
      'https://www.tesla.com/tesla-gallery',
      'https://www.tesla.com/themes/custom/tesla_frontend/assets/favicons/favicon-196x196.png',
      'image/png', 196, 196, 'c82462c37d740922a2e4dd0f5cc8f4da3d1e646453cfb3c525fae4f34864a6fc', 'reviewed_official_brand_icon'
    ),
    'thewaltdisneycompany.com': verifiedMakerLogo(
      'https://thewaltdisneycompany.com/',
      'https://thewaltdisneycompany.com/app/uploads/2026/01/icon-512x512-1.png',
      'image/png', 512, 512, '35b2316ecde11357ee2c8a01dd80fd62bef59e1f5d5aa1d0e78831e32219df99', 'apple_touch_icon'
    ),
    'netflix.com': verifiedMakerLogo(
      'https://about.netflix.com/en', 'https://about.netflix.com/images/meta/netflix-symbol-black.png',
      'image/png', 1198, 627, 'be8dc24c36708767813e4130bf56350a1c4abdf64579f83928580a147398ee5b', 'og_image'
    ),
    'nike.com': verifiedMakerLogo(
      'https://about.nike.com/en/newsroom/collections/nike-inc-logos',
      'https://nmp.about.nike.com/about/prod/cf68f541-fc92-4373-91cb-086ae0fe2f88/001-nike-logos-swoosh-black.jpg?m=eyJlZGl0cyI6eyJqcGVnIjp7InF1YWxpdHkiOjEwMH0sIndlYnAiOnsicXVhbGl0eSI6MTAwfSwiZXh0cmFjdCI6eyJsZWZ0IjowLCJ0b3AiOjAsIndpZHRoIjo1MDAwLCJoZWlnaHQiOjI4MTN9LCJyZXNpemUiOnsid2lkdGgiOjM4NDB9fX0%3D&s=57d350ee391a798ac553436b5e26b50a7e8b21d30bb4dd7a5538c2b249a0f10f',
      'image/jpeg', 3840, 2160, '61b44c30ddd67fadcf4df2305e21fefcd65a7ef0d4c5211ed7a53c64a8843c51', 'reviewed_media_asset', 'official_page_declared_cdn'
    ),
    'coca-colacompany.com': verifiedMakerLogo(
      'https://www.coca-colacompany.com/',
      'https://static-p58902-e658605.adobeaemcloud.com/be9f760d09fd66dd1beb8d07469e2184ac0c3f890a9fead200c5a0bf2277c166/resources/favicons/apple-touch-icon.png',
      'image/png', 180, 180, '4c12e06ed14b564e111d3ded968d084382966f11432904b7c9e104b80eb12f97', 'apple_touch_icon', 'official_page_declared_cdn'
    ),
    'corporate.mcdonalds.com': verifiedMakerLogo(
      'https://corporate.mcdonalds.com/corpmcd/home.html',
      'https://corporate.mcdonalds.com/content/dam/sites/corp/nfl/logo/mcd_corp_social_feed_default.jpg',
      'image/jpeg', 560, 400, 'e93b35c861fcdf643cd141bb8e288e788c4137aba2088e1f8514d5b5e7d0b776', 'icon'
    ),
  });

  const kosdaqCodes = new Set([
    '030530', '035760', '035900', '041510', '048910', '053030', '067160',
    '080160', '095700', '122870', '136480', '195500', '206560', '207760',
    '253450', '277810', '299900', '419530', '491000',
  ]);

  const stock = (id, name, nameEn, ticker, exchange, sector, officialDomain, aliases = []) => {
    const logo = verifiedMakerLogos[officialDomain] || null;
    const exactExchange = exchange === 'KRX' && /^\d{6}$/.test(ticker)
      ? (kosdaqCodes.has(ticker) ? 'KOSDAQ' : 'KOSPI')
      : exchange;
    return {
      id, name, company: name, name_en: nameEn, ticker, stock_code: ticker,
      exchange: exactExchange, market: exactExchange,
      sector, company_role_label: sector, official_domain: officialDomain, aliases,
      logo_url: '', logo_render_mode: 'initials', logo_minimum_dimension: 64,
      ...(logo || {}),
    };
  };

  const rows = [
    stock('kr-005930', '삼성전자', 'Samsung Electronics', '005930', 'KRX', '반도체·전자', 'samsung.com', ['삼전', 'samsung']),
    stock('kr-000660', 'SK하이닉스', 'SK hynix', '000660', 'KRX', '반도체', 'skhynix.com', ['하이닉스', 'sk hynix']),
    stock('kr-035420', 'NAVER', 'NAVER', '035420', 'KRX', '인터넷·플랫폼', 'navercorp.com', ['네이버']),
    stock('kr-035720', '카카오', 'Kakao', '035720', 'KRX', '인터넷·플랫폼', 'kakaocorp.com', ['kakao']),
    stock('kr-005380', '현대자동차', 'Hyundai Motor', '005380', 'KRX', '자동차', 'hyundai.com', ['현대차', 'hyundai']),
    stock('kr-000270', '기아', 'Kia', '000270', 'KRX', '자동차', 'kia.com', ['kia motors']),
    stock('kr-373220', 'LG에너지솔루션', 'LG Energy Solution', '373220', 'KRX', '배터리', 'lgensol.com', ['엘지에너지솔루션', 'lg엔솔']),
    stock('kr-207940', '삼성바이오로직스', 'Samsung Biologics', '207940', 'KRX', '바이오', 'samsungbiologics.com', ['삼바']),
    stock('kr-068270', '셀트리온', 'Celltrion', '068270', 'KRX', '바이오', 'celltrion.com', ['celltrion']),
    stock('kr-005490', 'POSCO홀딩스', 'POSCO Holdings', '005490', 'KRX', '철강·소재', 'posco-inc.com', ['포스코', 'posco']),
    stock('kr-105560', 'KB금융', 'KB Financial Group', '105560', 'KRX', '금융', 'kbfg.com', ['국민은행', 'kb']),
    stock('kr-055550', '신한지주', 'Shinhan Financial Group', '055550', 'KRX', '금융', 'shinhangroup.com', ['신한금융', 'shinhan']),
    stock('kr-086790', '하나금융지주', 'Hana Financial Group', '086790', 'KRX', '금융', 'hanafn.com', ['하나금융', 'hana']),
    stock('kr-323410', '카카오뱅크', 'KakaoBank', '323410', 'KRX', '인터넷은행', 'kakaobank.com', ['카뱅', 'kakaobank']),
    stock('kr-039490', '키움증권', 'Kiwoom Securities', '039490', 'KRX', '증권', 'kiwoom.com', ['키움', 'kiwoom']),
    stock('kr-006800', '미래에셋증권', 'Mirae Asset Securities', '006800', 'KRX', '증권', 'securities.miraeasset.com', ['미래에셋', 'mirae']),
    stock('kr-005940', 'NH투자증권', 'NH Investment & Securities', '005940', 'KRX', '증권', 'nhqv.com', ['엔에이치투자증권', 'nh']),
    stock('kr-097950', 'CJ제일제당', 'CJ CheilJedang', '097950', 'KRX', '식품', 'cj.co.kr', ['씨제이제일제당', 'cj']),
    stock('kr-004370', '농심', 'Nongshim', '004370', 'KRX', '식품', 'nongshim.com', ['nongshim']),
    stock('kr-007310', '오뚜기', 'Ottogi', '007310', 'KRX', '식품', 'ottogi.co.kr', ['ottogi']),
    stock('kr-271560', '오리온', 'Orion', '271560', 'KRX', '제과', 'orionworld.com', ['orion']),
    stock('kr-280360', '롯데웰푸드', 'Lotte Wellfood', '280360', 'KRX', '제과', 'lottewellfood.com', ['롯데제과', 'lotte']),
    stock('kr-136480', '하림', 'Harim', '136480', 'KOSDAQ', '식품', 'harim.com', ['harim']),
    stock('kr-049770', '동원F&B', 'Dongwon F&B', '049770', 'KRX', '식품·유통', 'dongwon.com', ['동원에프앤비', 'dongwon']),
    stock('kr-017810', '풀무원', 'Pulmuone', '017810', 'KRX', '식품', 'pulmuone.co.kr', ['pulmuone']),
    stock('kr-282330', 'BGF리테일', 'BGF Retail', '282330', 'KRX', '편의점·유통', 'cu.bgfretail.com', ['씨유', 'cu', 'bgf']),
    stock('kr-007070', 'GS리테일', 'GS Retail', '007070', 'KRX', '편의점·유통', 'gsretail.com', ['지에스리테일', 'gs25']),
    stock('kr-139480', '이마트', 'Emart', '139480', 'KRX', '대형마트·유통', 'company.emart.com', ['emart']),
    stock('kr-031440', '신세계푸드', 'Shinsegae Food', '031440', 'KRX', '식품·외식', 'shinsegaefood.com', ['신세계']),
    stock('kr-008770', '호텔신라', 'Hotel Shilla', '008770', 'KRX', '호텔·면세', 'shillahotels.com', ['신라호텔', 'shilla']),
    stock('kr-003490', '대한항공', 'Korean Air', '003490', 'KRX', '항공', 'koreanair.com', ['korean air']),
    stock('kr-012450', '한화에어로스페이스', 'Hanwha Aerospace', '012450', 'KRX', '항공우주·방산', 'hanwha.com', ['한화에어로', 'hanwha']),
    stock('kr-454910', '두산로보틱스', 'Doosan Robotics', '454910', 'KRX', '로봇', 'doosanrobotics.com', ['두산로봇']),
    stock('kr-277810', '레인보우로보틱스', 'Rainbow Robotics', '277810', 'KOSDAQ', '로봇', 'rainbow-robotics.com', ['레인보우', 'rainbow']),
    stock('kr-064350', '현대로템', 'Hyundai Rotem', '064350', 'KRX', '철도·방산', 'hyundai-rotem.co.kr', ['로템', 'rotem']),
    stock('kr-006400', '삼성SDI', 'Samsung SDI', '006400', 'KRX', '배터리', 'samsungsdi.com', ['삼성에스디아이', 'sdi']),
    stock('kr-051910', 'LG화학', 'LG Chem', '051910', 'KRX', '화학·배터리', 'lgchem.com', ['엘지화학']),
    stock('kr-096770', 'SK이노베이션', 'SK Innovation', '096770', 'KRX', '에너지·배터리', 'skinnovation.com', ['에스케이이노베이션']),
    stock('kr-090430', '아모레퍼시픽', 'Amorepacific', '090430', 'KRX', '뷰티', 'amorepacific.com', ['아모레', 'amore']),
    stock('kr-192820', '코스맥스', 'COSMAX', '192820', 'KRX', '화장품 ODM', 'cosmax.com', ['cosmax']),
    stock('kr-161890', '한국콜마', 'Kolmar Korea', '161890', 'KRX', '화장품 ODM', 'kolmar.co.kr', ['콜마', 'kolmar']),
    stock('kr-352820', '하이브', 'HYBE', '352820', 'KRX', '엔터테인먼트', 'hybecorp.com', ['hybe', '빅히트']),
    stock('kr-041510', '에스엠', 'SM Entertainment', '041510', 'KOSDAQ', '엔터테인먼트', 'smentertainment.com', ['sm', '에스엠엔터']),
    stock('kr-035900', 'JYP Ent.', 'JYP Entertainment', '035900', 'KOSDAQ', '엔터테인먼트', 'jype.com', ['제이와이피', 'jyp']),
    stock('kr-122870', '와이지엔터테인먼트', 'YG Entertainment', '122870', 'KOSDAQ', '엔터테인먼트', 'ygfamily.com', ['yg', '와이지']),
    stock('kr-253450', '스튜디오드래곤', 'Studio Dragon', '253450', 'KOSDAQ', '콘텐츠 제작', 'studiodragon.net', ['studio dragon']),
    stock('kr-207760', '미스터블루', 'Mr. Blue', '207760', 'KOSDAQ', '웹툰·웹소설', 'mrbluecorp.com', ['mr blue', '미스터 블루']),
    stock('kr-491000', '리브스메드', 'LivsMed', '491000', 'KOSDAQ', '의료기기', 'livsmed.com', ['livsmed']),
    stock('kr-251270', '넷마블', 'Netmarble', '251270', 'KRX', '게임', 'company.netmarble.com', ['netmarble']),
    stock('kr-036570', '엔씨소프트', 'NCSoft', '036570', 'KRX', '게임', 'nc.com', ['nc', 'ncsoft']),
    stock('kr-259960', '크래프톤', 'Krafton', '259960', 'KRX', '게임', 'krafton.com', ['배틀그라운드', 'krafton']),
    stock('us-AAPL', '애플', 'Apple', 'AAPL', 'NASDAQ', '전자·플랫폼', 'apple.com', ['apple', '아이폰']),
    stock('us-MSFT', '마이크로소프트', 'Microsoft', 'MSFT', 'NASDAQ', '소프트웨어·클라우드', 'microsoft.com', ['ms', 'microsoft']),
    stock('us-GOOGL', '알파벳', 'Alphabet', 'GOOGL', 'NASDAQ', '인터넷·AI', 'abc.xyz', ['구글', 'google']),
    stock('us-META', '메타 플랫폼스', 'Meta Platforms', 'META', 'NASDAQ', 'SNS·광고', 'about.meta.com', ['페이스북', '인스타그램', 'meta']),
    stock('us-AMZN', '아마존', 'Amazon', 'AMZN', 'NASDAQ', '이커머스·클라우드', 'amazon.com', ['aws', 'amazon']),
    stock('us-NVDA', '엔비디아', 'NVIDIA', 'NVDA', 'NASDAQ', '반도체·AI', 'nvidia.com', ['nvidia']),
    stock('us-TSLA', '테슬라', 'Tesla', 'TSLA', 'NASDAQ', '전기차·에너지', 'tesla.com', ['tesla']),
    stock('us-DIS', '월트 디즈니', 'The Walt Disney Company', 'DIS', 'NYSE', '콘텐츠·테마파크', 'thewaltdisneycompany.com', ['디즈니', 'disney']),
    stock('us-NFLX', '넷플릭스', 'Netflix', 'NFLX', 'NASDAQ', '스트리밍', 'netflix.com', ['netflix']),
    stock('us-NKE', '나이키', 'Nike', 'NKE', 'NYSE', '스포츠웨어', 'nike.com', ['nike']),
    stock('us-KO', '코카콜라', 'The Coca-Cola Company', 'KO', 'NYSE', '음료', 'coca-colacompany.com', ['coke', 'coca cola']),
    stock('us-MCD', '맥도날드', "McDonald's", 'MCD', 'NYSE', '외식', 'corporate.mcdonalds.com', ['mcdonalds']),
    stock('us-SBUX', '스타벅스', 'Starbucks', 'SBUX', 'NASDAQ', '카페', 'starbucks.com', ['starbucks']),
    stock('us-ADBE', '어도비', 'Adobe', 'ADBE', 'NASDAQ', '소프트웨어', 'adobe.com', ['adobe']),
    stock('us-SONY', '소니 그룹', 'Sony Group', 'SONY', 'NYSE', '전자·콘텐츠', 'sony.com', ['소니', 'sony']),
    stock('jp-7974', '닌텐도', 'Nintendo', '7974', 'TSE', '게임', 'nintendo.co.jp', ['nintendo']),
    stock('jp-7203', '도요타자동차', 'Toyota Motor', '7203', 'TSE', '자동차', 'global.toyota', ['토요타', 'toyota']),
    stock('us-SPOT', '스포티파이', 'Spotify', 'SPOT', 'NYSE', '음악 스트리밍', 'spotify.com', ['spotify']),
    stock('us-RBLX', '로블록스', 'Roblox', 'RBLX', 'NYSE', '게임·플랫폼', 'corp.roblox.com', ['roblox']),
  ];

  globalThis.TRZIP_STOCK_UNIVERSE = Object.freeze(rows.map((row, index) => Object.freeze({
    ...row,
    popular_rank: index < 12 ? index + 1 : null,
    recent_rank: [0, 1, 4, 14, 21, 32].includes(index) ? [0, 1, 4, 14, 21, 32].indexOf(index) + 1 : null,
  })));
})();
