import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { ArrowLeftIcon, QuestionIcon, SpinnerIcon } from '../components/ui/icons'
import AuthLayout from '../components/layout/AuthLayout'
import { authApi } from '../api/authApi'

type Step = 'username' | 'security_question' | 'reset_password' | 'success'

export default function ForgotPasswordPage() {
  const navigate = useNavigate()

  const [step, setStep] = useState<Step>('username')
  const [username, setUsername] = useState('')
  const [securityQuestion, setSecurityQuestion] = useState('')
  const [answer, setAnswer] = useState('')
  const [resetToken, setResetToken] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleUsernameSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)

    if (!username.trim()) {
      setError('Enter your username.')
      return
    }

    setIsSubmitting(true)
    try {
      const response = await authApi.forgotPassword(username)

      if (response.has_security_question && response.security_question) {
        setSecurityQuestion(response.security_question)
        setStep('security_question')
      } else {
        setError('This account has no security question set. Contact an administrator to reset your password.')
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not check that account. Try again.')
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleAnswerSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)

    if (!answer.trim()) {
      setError('Enter your answer.')
      return
    }

    setIsSubmitting(true)
    try {
      const response = await authApi.verifySecurityAnswer(username, answer)
      setResetToken(response.reset_token)
      setStep('reset_password')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'That answer is incorrect. Try again.')
    } finally {
      setIsSubmitting(false)
    }
  }

  const handlePasswordReset = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)

    if (newPassword.length < 6) {
      setError('Your password must be at least 6 characters.')
      return
    }

    if (newPassword !== confirmPassword) {
      setError('The passwords do not match. Re-enter them.')
      return
    }

    setIsSubmitting(true)
    try {
      await authApi.resetPassword(resetToken, newPassword)
      setStep('success')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not reset your password. Try again.')
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <AuthLayout
      title={step === 'success' ? 'Password changed' : 'Reset your password'}
      lead={
        step === 'username' ? 'Enter your username. You will answer the security question you set.'
          : step === 'security_question' ? 'Answer your security question.'
            : step === 'reset_password' ? 'Choose a new password.'
              : 'Sign in with your new password.'
      }
    >
        {/* Step 1: Username */}
        {step === 'username' && (
          <form onSubmit={handleUsernameSubmit} className="space-y-5">
            <div>
              <label htmlFor="forgot-username" className="block text-sm text-[var(--ink-muted)] mb-2">Username</label>
              <div className="relative">
                <input
                  id="forgot-username"
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  className="input-field"
                  placeholder="Enter your username"
                  autoComplete="username"
                />
              </div>
            </div>

            {error && (
              <div className="p-3 rounded-lg bg-alert-500/10 border border-alert-500/30 text-alert-400 text-sm">
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={isSubmitting}
              className="btn-cyber w-full flex items-center justify-center gap-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyber-300"
            >
              {isSubmitting ? <SpinnerIcon /> : null}
              Continue
            </button>
          </form>
        )}

        {/* Step 2: Security Question */}
        {step === 'security_question' && (
          <form onSubmit={handleAnswerSubmit} className="space-y-5">
            <div className="p-4 rounded-lg bg-void-800/50 border border-void-700">
              <div className="flex items-start gap-3">
                <QuestionIcon className="text-cyber-400 text-lg mt-0.5" />
                <p className="text-[var(--ink)]">{securityQuestion}</p>
              </div>
            </div>

            <div>
              <label htmlFor="forgot-answer" className="block text-sm text-[var(--ink-muted)] mb-2">Your answer</label>
              <input
                id="forgot-answer"
                type="text"
                value={answer}
                onChange={(e) => setAnswer(e.target.value)}
                className="input-field"
                placeholder="Enter your answer"
                autoComplete="off"
              />
            </div>

            {error && (
              <div className="p-3 rounded-lg bg-alert-500/10 border border-alert-500/30 text-alert-400 text-sm">
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={isSubmitting}
              className="btn-cyber w-full flex items-center justify-center gap-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyber-300"
            >
              {isSubmitting ? <SpinnerIcon /> : null}
              Verify answer
            </button>
          </form>
        )}

        {/* Step 3: Reset Password */}
        {step === 'reset_password' && (
          <form onSubmit={handlePasswordReset} className="space-y-5">
            <div>
              <label htmlFor="forgot-new-password" className="block text-sm text-[var(--ink-muted)] mb-2">New password</label>
              <div className="relative">
                <input
                  id="forgot-new-password"
                  type="password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  className="input-field"
                  placeholder="Enter a new password"
                  autoComplete="new-password"
                />
              </div>
            </div>

            <div>
              <label htmlFor="forgot-confirm-password" className="block text-sm text-[var(--ink-muted)] mb-2">Confirm password</label>
              <div className="relative">
                <input
                  id="forgot-confirm-password"
                  type="password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  className="input-field"
                  placeholder="Re-enter your new password"
                  autoComplete="new-password"
                />
              </div>
            </div>

            {error && (
              <div className="p-3 rounded-lg bg-alert-500/10 border border-alert-500/30 text-alert-400 text-sm">
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={isSubmitting}
              className="btn-cyber w-full flex items-center justify-center gap-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyber-300"
            >
              {isSubmitting ? <SpinnerIcon /> : null}
              Reset password
            </button>
          </form>
        )}

        {/* Step 4: Success */}
        {step === 'success' && (
          <div>
            <button
              onClick={() => navigate('/login')}
              className="btn-cyber w-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyber-300"
            >
              Go to sign in
            </button>
          </div>
        )}

        {/* Back to login */}
        {step !== 'success' && (
          <div className="mt-8">
            <Link
              to="/login"
              className="inline-flex items-center gap-2 text-sm text-[var(--ink-muted)] hover:text-cyber-400 transition-colors rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyber-500/60"
            >
              <ArrowLeftIcon />
              Back to sign in
            </Link>
          </div>
        )}
    </AuthLayout>
  )
}
