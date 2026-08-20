import { type FormEvent, useState } from "react";
import { LockKeyhole, TrendingUp } from "lucide-react";

type LoginPageProps = {
  onLogin: (password: string) => Promise<void>;
  error?: string;
};

export default function LoginPage({ onLogin, error = "" }: LoginPageProps) {
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setFormError("");
    try {
      await onLogin(password);
    } catch (loginError) {
      setFormError(loginError instanceof Error ? loginError.message : "登录失败，请稍后重试。");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="loginPage">
      <section className="loginCard" aria-labelledby="login-title">
        <div className="loginBrand"><TrendingUp size={23} aria-hidden="true" /> Stock Ranking</div>
        <h1 id="login-title">登录后查看市场数据</h1>
        <p>输入访问密码以查看股票强度、资金流和事件监测。</p>
        <form onSubmit={submit}>
          <label>
            <span>访问密码</span>
            <input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required />
          </label>
          {formError || error ? <div className="loginError">{formError || error}</div> : null}
          <button className="loginButton" type="submit" disabled={submitting}>
            <LockKeyhole size={16} aria-hidden="true" />
            {submitting ? "正在登录…" : "登录"}
          </button>
        </form>
      </section>
    </main>
  );
}
