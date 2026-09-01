# new_data/fuel/source.md
TTF=F     Dutch TTF Natural Gas   EUR/MWh    yfinance (Yahoo Finance)
MTF=F     Coal API2 CIF ARA       USD/公噸    yfinance
EURUSD=X  歐元/美元匯率                        yfinance   ← 煤價換算用

碳價 EUA 不在這裡抓,原料在 ../carbon_price_ICAP/(ICAP Allowance Price Explorer)
🔴 舊來源 Yahoo CO2.L 已淘汰:只回到 2021-10(涵蓋 52%);
   重疊期與 ICAP corr 0.986、中位差 €1.41(拍賣 vs 期貨基差)

dst_kn8y_biomass_trade_raw    Danmarks Statistik KN8Y(生質貿易)
se_energimyndigheten_tradbransle  瑞典能源署 木燃料價格

儲存原則:raw。USD→EUR、公噸→MWh 的換算在 load_duckdb.build_fuel,不在這裡。




商品	指數	       管道
天然氣	 TTF	       🟡 Yahoo(TTF=F)
煤	    API2 CIF ARA  🟡 Yahoo(MTF=F)
匯率	EUR/USD	      🟡 Yahoo(EURUSD=X)
碳	    EUA	          ✅ ICAP 手動下載
生質 A	丹麥海關    	✅ api.statbank.dk 官方 API
生質 B	瑞典能源署  	✅ pxexternal.energimyndigheten.se 官方 API