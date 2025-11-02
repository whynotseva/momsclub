BEGIN;
CREATE TEMP TABLE tmp_users(name TEXT);
INSERT INTO tmp_users(name) VALUES
('anastasia_tokareva'),
('dr_koshelnikova'),
('Guzalya234'),
('vikka_labkovich'),
('alya_vy'),
('tanyashkrebets'),
('lilya_dubovitskaya'),
('loloshkaNa'),
('annagerman_ph'),
('elnuraskv'),
('alina7re'),
('yuermakovva'),
('Polina_gf');
WITH target_users AS (
  SELECT u.id as user_id FROM users u JOIN tmp_users t ON lower(u.username) = lower(t.name)
), latest_active AS (
  SELECT s.id as sub_id FROM subscriptions s JOIN target_users tu ON tu.user_id = s.user_id
  WHERE s.is_active = 1 AND strftime('%Y', s.end_date) < '2100' AND s.end_date = (
    SELECT MAX(s2.end_date) FROM subscriptions s2 WHERE s2.user_id = s.user_id AND s2.is_active = 1
  )
)
UPDATE subscriptions SET end_date = datetime(end_date, '+3 day') WHERE id IN (SELECT sub_id FROM latest_active);
COMMIT;
SELECT u.username, s.end_date as new_end_date FROM users u JOIN subscriptions s ON s.user_id = u.id
WHERE lower(u.username) IN (SELECT lower(name) FROM tmp_users) AND s.is_active = 1 AND s.end_date = (
  SELECT MAX(s2.end_date) FROM subscriptions s2 WHERE s2.user_id = u.id AND s2.is_active = 1
) ORDER BY u.username;
