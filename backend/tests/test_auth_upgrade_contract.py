import copy
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

try:
    from app import server as backend_app
    from app.api import auth as auth_module
    from app.services import auth_credentials

    _APP_IMPORT_ERROR = ""
except Exception as exc:
    backend_app = None
    _APP_IMPORT_ERROR = str(exc)


@unittest.skipIf(backend_app is None, f"backend app unavailable: {_APP_IMPORT_ERROR}")
class TestAuthUpgradeContract(unittest.TestCase):
    def setUp(self):
        backend_app.app.testing = True
        self.client = backend_app.app.test_client()
        self.users = {}
        self.sessions = {}
        self.events = {}
        self.tmpdir = tempfile.mkdtemp(prefix="fzg-auth-")
        self.credentials_file = os.path.join(self.tmpdir, "auth_credentials.json")
        auth_module.reset_login_state()

    def tearDown(self):
        auth_module.reset_login_state()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # ---------- 存储桩 ----------

    def _storage(self):
        def get_auth_user(username):
            item = self.users.get(username)
            return copy.deepcopy(item) if item else None

        def get_auth_user_by_display_name(display_name):
            key = str(display_name or "").strip().casefold()
            for item in self.users.values():
                if str(item.get("display_name") or "").strip().casefold() == key:
                    return copy.deepcopy(item)
            return None

        def upsert_auth_user(user):
            self.users[user["username"]] = copy.deepcopy(user)
            return copy.deepcopy(user)

        def get_auth_session_by_token_hash(token_hash):
            item = self.sessions.get(token_hash)
            return copy.deepcopy(item) if item else None

        def upsert_auth_session(data):
            self.sessions[data["token_hash"]] = copy.deepcopy(data)
            return copy.deepcopy(data)

        def revoke_auth_session(token_hash, revoked_at):
            item = self.sessions.get(token_hash)
            if not item:
                return False
            item["revoked_at"] = revoked_at
            return True

        def touch_auth_session(token_hash, last_seen_at):
            item = self.sessions.get(token_hash)
            if not item:
                return False
            item["last_seen_at"] = last_seen_at
            return True

        def list_auth_sessions(username):
            return [
                copy.deepcopy(item)
                for item in self.sessions.values()
                if item.get("username") == username
            ]

        def revoke_other_auth_sessions(username, keep_token_hash, revoked_at):
            count = 0
            for token_hash, item in self.sessions.items():
                if item.get("username") != username:
                    continue
                if keep_token_hash and token_hash == keep_token_hash:
                    continue
                if item.get("revoked_at"):
                    continue
                item["revoked_at"] = revoked_at
                count += 1
            return count

        def append_user_event(user_id, suffix, item):
            self.events.setdefault((user_id, suffix), []).append(copy.deepcopy(item))

        def load_user_event_list(user_id, suffix):
            return copy.deepcopy(self.events.get((user_id, suffix), []))

        return patch.multiple(
            backend_app,
            get_auth_user=get_auth_user,
            get_auth_user_by_display_name=get_auth_user_by_display_name,
            upsert_auth_user=upsert_auth_user,
            get_auth_session_by_token_hash=get_auth_session_by_token_hash,
            upsert_auth_session=upsert_auth_session,
            revoke_auth_session=revoke_auth_session,
            touch_auth_session=touch_auth_session,
            list_auth_sessions=list_auth_sessions,
            revoke_other_auth_sessions=revoke_other_auth_sessions,
            append_user_event=append_user_event,
            load_user_event_list=load_user_event_list,
        )

    def _credentials(self):
        return patch.object(auth_credentials, "_FILE_PATH", self.credentials_file)

    # ---------- 辅助 ----------

    def _register(self, username="student_a", password="secret123", display="小坊"):
        return self.client.post(
            "/api/auth/register",
            json={"username": username, "password": password, "display_name": display},
        )

    def _login(self, password="secret123", username="student_a", **extra):
        payload = {"username": username, "password": password}
        payload.update(extra)
        return self.client.post("/api/auth/login", json=payload)

    def _token(self, resp):
        return ((resp.get_json() or {}).get("auth") or {}).get("token", "")

    # ---------- 恢复码 ----------

    def test_register_returns_recovery_code(self):
        with self._storage(), self._credentials():
            resp = self._register()

        self.assertEqual(200, resp.status_code)
        code = (resp.get_json() or {}).get("recovery_code", "")
        self.assertRegex(code, r"^[A-Z2-9]{4}-[A-Z2-9]{4}$")

    def test_recovery_code_resets_password(self):
        with self._storage(), self._credentials():
            code = (self._register().get_json() or {}).get("recovery_code")
            reset = self.client.post(
                "/api/auth/recovery/reset",
                json={
                    "username": "student_a",
                    "recovery_code": code,
                    "new_password": "newpass123",
                },
            )
            old_login = self._login("secret123")
            new_login = self._login("newpass123")

        self.assertEqual(200, reset.status_code)
        self.assertEqual(401, old_login.status_code)
        self.assertEqual(200, new_login.status_code)

    def test_recovery_rejects_wrong_code(self):
        with self._storage(), self._credentials():
            self._register()
            resp = self.client.post(
                "/api/auth/recovery/reset",
                json={
                    "username": "student_a",
                    "recovery_code": "AAAA-BBBB",
                    "new_password": "newpass123",
                },
            )

        self.assertEqual(400, resp.status_code)
        self.assertEqual("RECOVERY_FAILED", (resp.get_json() or {}).get("error_code"))

    def test_recovery_unknown_account_not_disclosed(self):
        with self._storage(), self._credentials():
            resp = self.client.post(
                "/api/auth/recovery/reset",
                json={
                    "username": "not_exist",
                    "recovery_code": "AAAA-BBBB",
                    "new_password": "newpass123",
                },
            )

        self.assertEqual(400, resp.status_code)
        self.assertEqual("RECOVERY_FAILED", (resp.get_json() or {}).get("error_code"))

    # ---------- 密码强度 ----------

    def test_weak_password_rejected(self):
        with self._storage(), self._credentials():
            resp = self._register(password="secret")

        self.assertEqual(400, resp.status_code)
        self.assertEqual("WEAK_PASSWORD", (resp.get_json() or {}).get("error_code"))

    def test_password_requires_letter_and_digit(self):
        with self._storage(), self._credentials():
            letters_only = self._register(username="u_letters", password="abcdefghij")
            digits_only = self._register(username="u_digits", password="1234567890")

        self.assertEqual("WEAK_PASSWORD", (letters_only.get_json() or {}).get("error_code"))
        self.assertEqual("WEAK_PASSWORD", (digits_only.get_json() or {}).get("error_code"))

    # ---------- 修改密码 ----------

    def test_change_password_flow(self):
        with self._storage(), self._credentials():
            headers = {"Authorization": f"Bearer {self._token(self._register())}"}

            wrong_old = self.client.post(
                "/api/auth/change-password",
                headers=headers,
                json={"old_password": "bad-old-1", "new_password": "newpass123"},
            )
            ok = self.client.post(
                "/api/auth/change-password",
                headers=headers,
                json={"old_password": "secret123", "new_password": "newpass123"},
            )
            old_login = self._login("secret123")
            new_login = self._login("newpass123")

        self.assertEqual(401, wrong_old.status_code)
        self.assertEqual(200, ok.status_code)
        self.assertEqual(401, old_login.status_code)
        self.assertEqual(200, new_login.status_code)

    def test_change_password_revokes_other_sessions(self):
        with self._storage(), self._credentials():
            first = self._register()
            second = self._login()
            first_headers = {"Authorization": f"Bearer {self._token(first)}"}
            second_headers = {"Authorization": f"Bearer {self._token(second)}"}

            change = self.client.post(
                "/api/auth/change-password",
                headers=first_headers,
                json={"old_password": "secret123", "new_password": "newpass123"},
            )
            kept = self.client.get("/api/auth/me", headers=first_headers)
            kicked = self.client.get("/api/auth/me", headers=second_headers)

        self.assertEqual(200, change.status_code)
        self.assertEqual(200, kept.status_code)
        self.assertEqual(401, kicked.status_code)

    # ---------- 资料编辑 ----------

    def test_update_profile_changes_display_name(self):
        with self._storage(), self._credentials():
            headers = {"Authorization": f"Bearer {self._token(self._register())}"}
            resp = self.client.put(
                "/api/auth/profile",
                headers=headers,
                json={"display_name": "新昵称", "bio": "纺织工程专业，正在准备材料学期中考试。"},
            )
            me = self.client.get("/api/auth/me", headers=headers)

        payload = (resp.get_json() or {}).get("user") or {}
        self.assertEqual(200, resp.status_code)
        self.assertEqual("新昵称", payload.get("display_name"))
        self.assertEqual("纺织工程专业，正在准备材料学期中考试。", payload.get("bio"))

        me_user = ((me.get_json() or {}).get("auth") or {}).get("user") or {}
        self.assertEqual("新昵称", me_user.get("display_name"))
        self.assertEqual("纺织工程专业，正在准备材料学期中考试。", me_user.get("bio"))

    def test_update_profile_truncates_long_bio(self):
        with self._storage(), self._credentials():
            headers = {"Authorization": f"Bearer {self._token(self._register())}"}
            resp = self.client.put(
                "/api/auth/profile",
                headers=headers,
                json={"bio": "长" * 900},
            )

        self.assertEqual(200, resp.status_code)
        self.assertEqual(500, len(((resp.get_json() or {}).get("user") or {}).get("bio") or ""))

    def test_update_profile_locale_persists(self):
        with self._storage(), self._credentials():
            headers = {"Authorization": f"Bearer {self._token(self._register())}"}
            self.client.put("/api/auth/profile", headers=headers, json={"locale": "EN"})
            me = self.client.get("/api/auth/me", headers=headers)

        self.assertEqual(
            "EN",
            ((me.get_json() or {}).get("auth") or {}).get("user", {}).get("locale"),
        )

    def test_update_profile_rejects_duplicate_display_name(self):
        with self._storage(), self._credentials():
            self._register(username="student_a", display="小坊")
            other = self._register(username="student_b", display="小杭")
            headers = {"Authorization": "Bearer " + self._token(other)}
            resp = self.client.put(
                "/api/auth/profile",
                headers=headers,
                json={"display_name": "小坊"},
            )

        self.assertEqual(409, resp.status_code)
        self.assertEqual("AUTH_DISPLAY_NAME_EXISTS", (resp.get_json() or {}).get("error_code"))

    def test_update_profile_requires_login(self):
        with self._storage(), self._credentials():
            resp = self.client.put(
                "/api/auth/profile",
                json={"display_name": "匿名"},
            )

        self.assertEqual(401, resp.status_code)

    # ---------- 登录防护 ----------

    def test_login_locked_after_repeated_failures(self):
        with self._storage(), self._credentials():
            self._register()
            codes = [
                self._login("wrongpass1").status_code
                for _ in range(6)
            ]

        self.assertEqual(401, codes[0])
        self.assertIn(429, codes)
        self.assertEqual(429, codes[-1])

    def test_successful_login_clears_failure_counter(self):
        with self._storage(), self._credentials():
            self._register()
            for _ in range(3):
                self._login("wrongpass1")
            good = self._login("secret123")
            after = self._login("wrongpass1")

        self.assertEqual(200, good.status_code)
        self.assertEqual(401, after.status_code, "成功登录后计数应清零，不立即锁定")

    # ---------- 会话管理 ----------

    def test_sessions_list_marks_current(self):
        with self._storage(), self._credentials():
            first = self._register()
            self._login()
            resp = self.client.get(
                "/api/auth/sessions",
                headers={"Authorization": f"Bearer {self._token(first)}"},
            )

        sessions = (resp.get_json() or {}).get("sessions") or []
        self.assertEqual(200, resp.status_code)
        self.assertEqual(2, len(sessions))
        self.assertEqual(1, len([item for item in sessions if item.get("current")]))

    def test_revoke_all_other_sessions(self):
        with self._storage(), self._credentials():
            first = self._register()
            second = self._login()
            first_headers = {"Authorization": f"Bearer {self._token(first)}"}
            second_headers = {"Authorization": f"Bearer {self._token(second)}"}

            resp = self.client.post(
                "/api/auth/sessions/revoke",
                headers=first_headers,
                json={"all_others": True},
            )
            kicked = self.client.get("/api/auth/me", headers=second_headers)

        self.assertEqual(200, resp.status_code)
        self.assertEqual(1, (resp.get_json() or {}).get("revoked"))
        self.assertEqual(401, kicked.status_code)

    def test_cannot_revoke_current_session(self):
        with self._storage(), self._credentials():
            first = self._register()
            headers = {"Authorization": f"Bearer {self._token(first)}"}
            session_id = ((first.get_json() or {}).get("auth") or {}).get("session_id")

            resp = self.client.post(
                "/api/auth/sessions/revoke",
                headers=headers,
                json={"session_id": session_id},
            )

        self.assertEqual(400, resp.status_code)

    # ---------- 游客数据继承 ----------

    def test_login_does_not_adopt_guest_by_default(self):
        with self._storage(), self._credentials():
            self._register()
            with patch.object(backend_app, "bind_guest_user_data_to_auth_user") as mocked:
                self._login(guest_user_id="guest_abcd1234")

        mocked.assert_not_called()

    def test_login_adopts_guest_when_confirmed(self):
        with self._storage(), self._credentials():
            self._register()
            with patch.object(backend_app, "bind_guest_user_data_to_auth_user") as mocked:
                mocked.return_value = {
                    "guest_user_id": "guest_abcd1234",
                    "user_id": "student_a",
                    "migrated": True,
                    "plans": 1,
                    "spaces": 0,
                    "space_items": 0,
                    "concepts": 2,
                    "relations": 0,
                    "knowledge_updated": True,
                    "events": 0,
                    "message": "",
                }
                resp = self._login(
                    guest_user_id="guest_abcd1234",
                    adopt_guest_data=True,
                )
                mocked.assert_called_once()

        self.assertEqual(200, resp.status_code)
        self.assertTrue(((resp.get_json() or {}).get("binding") or {}).get("migrated"))

    def test_register_binds_guest_data(self):
        with self._storage(), self._credentials():
            with patch.object(backend_app, "bind_guest_user_data_to_auth_user") as mocked:
                mocked.return_value = {
                    "guest_user_id": "guest_abcd1234",
                    "user_id": "student_new",
                    "migrated": True,
                    "plans": 2,
                    "spaces": 1,
                    "space_items": 3,
                    "concepts": 5,
                    "relations": 4,
                    "knowledge_updated": True,
                    "events": 6,
                    "message": "",
                }
                resp = self.client.post(
                    "/api/auth/register",
                    json={
                        "username": "student_new",
                        "password": "secret123",
                        "display_name": "新同学",
                        "guest_user_id": "guest_abcd1234",
                    },
                )
                mocked.assert_called_once()

        self.assertEqual(200, resp.status_code)
        binding = (resp.get_json() or {}).get("binding") or {}
        self.assertTrue(binding.get("migrated"))
        self.assertEqual(2, binding.get("plans"))


if __name__ == "__main__":
    unittest.main()
