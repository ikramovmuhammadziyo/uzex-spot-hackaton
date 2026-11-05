"""Read-only registry integrity primitives; all values are computed from the snapshot."""

REGISTRY_AUDIT_SQL = """
WITH inventory AS (
 SELECT COUNT(*) deals_count, COUNT(DISTINCT deal_no) unique_deal_numbers,
   MIN(deal_no) min_deal_number, MAX(deal_no) max_deal_number,
   MAX(deal_no)-MIN(deal_no)+1 number_span,
   MAX(deal_no)-MIN(deal_no)+1-COUNT(DISTINCT deal_no) deal_number_gaps,
   COUNT(DISTINCT deal_date) trading_days, MIN(deal_date) first_deal_date, MAX(deal_date) last_deal_date,
   COUNT(DISTINCT seller_inn) active_sellers, COUNT(DISTINCT buyer_inn) active_buyers,
   COUNT(DISTINCT seller_broker) active_seller_brokers,
   COUNT(*) FILTER (WHERE EXTRACT(ISODOW FROM deal_date) IN (6,7)) weekend_deals
 FROM deals
), contract_stats AS (
 SELECT COUNT(*) contracts_registered,
   COUNT(*) FILTER (WHERE u.contract_no IS NOT NULL) contracts_used,
   COUNT(*) FILTER (WHERE u.contract_no IS NULL) contracts_unused,
   COUNT(*) FILTER (WHERE u.contract_no IS NULL AND c.currency='UZS') unused_contracts_uzs,
   COUNT(*) FILTER (WHERE u.contract_no IS NULL AND c.currency='USD') unused_contracts_usd
 FROM contracts c LEFT JOIN (SELECT DISTINCT contract_no FROM deals) u USING(contract_no)
), trading_companies AS (
 SELECT seller_inn AS inn FROM deals UNION SELECT buyer_inn FROM deals
), company_stats AS (
 SELECT COUNT(*) participants_registered,
   COUNT(*) FILTER (WHERE t.inn IS NOT NULL) participants_trading,
   COUNT(*) FILTER (WHERE t.inn IS NULL) participants_unused
 FROM participants p LEFT JOIN trading_companies t USING(inn)
), broker_stats AS (
 SELECT COUNT(*) brokers_registered,
   COUNT(*) FILTER (WHERE u.code IS NULL) brokers_never_seller
 FROM brokers b LEFT JOIN (SELECT DISTINCT seller_broker AS code FROM deals) u USING(code)
), rate_changes AS (
 SELECT date, rate, LAG(rate) OVER (ORDER BY date) AS previous_rate FROM usd_rates
), rate_stats AS (
 SELECT COUNT(*) rate_rows, COUNT(DISTINCT date) rate_dates,
   MIN(date) first_rate_date, MAX(date) last_rate_date,
   MIN(rate) min_rate, MAX(rate) max_rate,
   DATE_DIFF('day',MIN(date),MAX(date))+1-COUNT(DISTINCT date) missing_rate_calendar_days,
   COUNT(*) FILTER (WHERE rate < previous_rate) rate_down_days,
   COUNT(*) FILTER (WHERE rate > previous_rate) rate_up_days,
   COUNT(*) FILTER (WHERE rate = previous_rate) rate_flat_days,
   COUNT(*) FILTER (WHERE rate IS NULL) null_rates
 FROM rate_changes
), orphan_stats AS (
 SELECT COUNT(*) FILTER (WHERE c.contract_no IS NULL OR s.inn IS NULL OR b.inn IS NULL
                         OR sb.code IS NULL OR bb.code IS NULL) orphan_deals,
   COUNT(*) FILTER (WHERE r.date IS NULL) deals_without_rate
 FROM deals d LEFT JOIN contracts c USING(contract_no)
 LEFT JOIN participants s ON s.inn=d.seller_inn
 LEFT JOIN participants b ON b.inn=d.buyer_inn
 LEFT JOIN brokers sb ON sb.code=d.seller_broker
 LEFT JOIN brokers bb ON bb.code=d.buyer_broker
 LEFT JOIN usd_rates r ON r.date=d.deal_date
)
SELECT * FROM inventory CROSS JOIN contract_stats CROSS JOIN company_stats
 CROSS JOIN broker_stats CROSS JOIN rate_stats CROSS JOIN orphan_stats
"""
