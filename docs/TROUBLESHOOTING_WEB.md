# Диагностика: не открывается веб-интерфейс

Если в логах API и frontend нет явных ошибок, по шагам проверьте цепочку: браузер → Caddy (80/443) → frontend и API.

---

## 1. Кто слушает порты 80 и 443

Входная точка — **Caddy**. Если до него запрос не доходит или Caddy не слушает нужный хост, страница не откроется.

На хосте (вне Docker):

```bash
# Кто слушает 80 и 443
sudo ss -tlnp | grep -E ':80|:443'
# или
sudo netstat -tlnp | grep -E ':80|:443'
```

Ожидается: процесс **caddy** (или docker-proxy) на 0.0.0.0:80 и 0.0.0.0:443.  
Если порты заняты nginx/apache/другим — остановите их или смените порты Caddy в `docker-compose.yml`.

---

## 2. Состояние контейнеров

```bash
docker compose ps
```

Проверьте:

- **caddy** — `Up (healthy)` или хотя бы `Up`.
- **frontend** — `Up`.
- **api** — `Up (healthy)` или `Up`.

Если caddy в состоянии `Restarting` или `Exit` — смотрите логи Caddy (шаг 4).  
Если frontend не запущен — поднимайте и смотрите логи frontend.

---

## 3. Какой адрес открываете

Caddy слушает только тот хост, который задан в `.env` как **SERVER_HOST**.

Проверьте:

```bash
grep SERVER_HOST .env
```

Открывать в браузере нужно **именно этот хост** (и желательно по HTTPS):

- Если `SERVER_HOST=ai.example.com` — открывайте `https://ai.example.com`.
- Если `SERVER_HOST=192.168.1.100` — открывайте `https://192.168.1.100`.
- Если открываете `http://localhost` при `SERVER_HOST=192.168.1.100` — Caddy на localhost может не отвечать (зависит от конфига).

Проверка с хоста:

```bash
curl -k -s -o /dev/null -w "%{http_code}" "https://$(grep SERVER_HOST .env | cut -d= -f2)/"
```

Ожидается 200 (или 304). Если `000` или таймаут — запрос до Caddy не доходит (сеть, firewall, неверный хост).

---

## 4. Логи Caddy

```bash
docker compose logs caddy --tail 100
```

Смотрите:

- Ошибки при старте (не удалось привязать порт, ошибка конфига).
- Сообщения вида `[Caddy] Режим: ...` — подтверждение, что entrypoint сработал и какой хост используется.
- Ошибки TLS (сертификат, Let's Encrypt).

Если в логах есть `connection refused` до `frontend:3000` или `api:8000` — проблема в сети Docker или в том, что frontend/api не готовы/не запущены.

---

## 5. Доступность frontend и API изнутри сети Docker

Caddy обращается к `frontend:3000` и `api:8000` по имени сервиса. Проверка из контейнера Caddy:

```bash
docker compose exec caddy wget -qO- --timeout=3 http://frontend:3000/ | head -c 200
docker compose exec caddy wget -qO- --timeout=3 http://api:8000/health 2>/dev/null || true
```

Если здесь таймаут или connection refused — frontend или API для Caddy недоступны (сеть, зависание при старте).

---

## 6. Прямая проверка frontend (минуя Caddy)

Временно привяжите порт frontend к хосту в `docker-compose.yml` (например, `ports: - "3000:3000"`), перезапустите frontend и откройте в браузере `http://localhost:3000`.

- Если так страница открывается — проблема в Caddy или в том, как вы заходите на Caddy (хост, порт, HTTP/HTTPS).
- Если и так не открывается — проблема во frontend (сборка, рантайм, белый экран — тогда смотреть консоль браузера F12).

---

## 7. Типичные причины

| Симптом | Что проверить |
|--------|----------------|
| Таймаут при открытии страницы | Firewall (80/443), правильный ли SERVER_HOST и адрес в браузере. |
| «Сайт недоступен» / connection refused | Caddy не запущен или не слушает 80/443; порты заняты другим процессом. |
| 502 Bad Gateway | Caddy не может достучаться до frontend:3000 или api:8000 — смотреть логи Caddy, состояние frontend и api. |
| Белый экран, в логах API/frontend тихо | Ошибки в браузере (F12 → Console/Network), неверный BASE_URL или CORS. |
| Редирект на неверный хост | В .env другой SERVER_HOST — открывать тот же хост, что в SERVER_HOST. |

---

## 8. Быстрый скрипт проверки

Сохраните как `scripts/check-web.sh` и запустите из корня проекта:

```bash
#!/bin/bash
set -e
cd "$(dirname "$0")/.."
echo "=== 1. Порты 80/443 ==="
sudo ss -tlnp 2>/dev/null | grep -E ':80 |:443 ' || true
echo ""
echo "=== 2. Контейнеры ==="
docker compose ps
echo ""
echo "=== 3. SERVER_HOST ==="
grep SERVER_HOST .env 2>/dev/null || echo ".env не найден или SERVER_HOST не задан"
echo ""
echo "=== 4. Проверка ответа Caddy (curl по SERVER_HOST) ==="
H=$(grep '^SERVER_HOST=' .env 2>/dev/null | cut -d= -f2- | tr -d '"')
if [ -n "$H" ]; then
  curl -k -s -o /dev/null -w "HTTPS %{http_code} -> https://$H/\n" "https://$H/" || echo "curl не удался"
else
  echo "SERVER_HOST пуст, пропуск curl"
fi
echo ""
echo "=== 5. Последние логи Caddy ==="
docker compose logs caddy --tail 15
```

После выполнения по шагам 1–5 обычно видно, на каком звене цепочки проблема (порты, Caddy, frontend, адрес в браузере).
