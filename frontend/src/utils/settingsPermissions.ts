export type PermissionKey =
  | 'create_task'
  | 'start_task'
  | 'manage_task_status'
  | 'delete_task'
  | 'upload_task_spec'
  | 'manage_skills'
  | 'manage_members'
  | 'view_dashboard'
  | 'view_assets'
  | 'manage_requirements'
  | 'export_task'
  | 'view_api_mock'
  | 'manage_api_mock'
  | 'publish_api_mock'

export type PermissionFlags = Record<PermissionKey, boolean>

export const createEmptyPermissions = (override?: Partial<PermissionFlags>): PermissionFlags => ({
  create_task: false,
  start_task: false,
  manage_task_status: false,
  delete_task: false,
  upload_task_spec: false,
  manage_skills: false,
  manage_members: false,
  view_dashboard: true,
  view_assets: true,
  manage_requirements: false,
  export_task: false,
  view_api_mock: false,
  manage_api_mock: false,
  publish_api_mock: false,
  ...override,
})

export const defaultPermissionsByRole = (role: 'OWNER' | 'DEVELOPER' | 'VIEWER'): PermissionFlags => {
  if (role === 'OWNER') {
    return createEmptyPermissions({
      create_task: true,
      start_task: true,
      manage_task_status: true,
      delete_task: true,
      upload_task_spec: true,
      manage_skills: true,
      manage_members: true,
      view_dashboard: true,
      view_assets: true,
      manage_requirements: true,
      export_task: true,
      view_api_mock: true,
      manage_api_mock: true,
      publish_api_mock: true,
    })
  }

  if (role === 'DEVELOPER') {
    return createEmptyPermissions({
      create_task: true,
      start_task: true,
      manage_task_status: true,
      delete_task: true,
      upload_task_spec: true,
      manage_skills: true,
      view_dashboard: true,
      view_assets: true,
      manage_requirements: false,
      export_task: true,
      view_api_mock: true,
      manage_api_mock: true,
    })
  }

  return createEmptyPermissions({
    view_dashboard: true,
    view_assets: true,
    view_api_mock: true,
  })
}
