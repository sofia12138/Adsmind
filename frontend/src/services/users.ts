import { apiFetch } from './api'

export interface UserInfo {
  id?: number
  username: string
  role: string
  display_name: string
  assigned_accounts: string[]
  email?: string
}

export interface CreateUserBody {
  username: string
  password: string
  role?: string
  display_name?: string
  assigned_accounts?: string[]
}

export interface UpdateUserBody {
  password?: string
  role?: string
  display_name?: string
  assigned_accounts?: string[]
}

export async function fetchUsers(): Promise<UserInfo[]> {
  return apiFetch<UserInfo[]>('/api/users/')
}

export async function createUser(body: CreateUserBody): Promise<UserInfo> {
  return apiFetch<UserInfo>('/api/users/', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export async function updateUser(username: string, body: UpdateUserBody): Promise<UserInfo> {
  return apiFetch<UserInfo>(`/api/users/${username}`, {
    method: 'PUT',
    body: JSON.stringify(body),
  })
}

export async function deleteUser(username: string): Promise<void> {
  await apiFetch<{ ok: boolean }>(`/api/users/${username}`, {
    method: 'DELETE',
  })
}
