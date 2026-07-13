# reset_admin.rb

puts "--- Running Chatwoot Account Setup/Reset Script ---"

# Check accounts
account = Account.first
if account.nil?
  account = Account.create!(name: "Default Account")
  puts "Created Default Account."
else
  puts "Found existing account: #{account.name} (ID: #{account.id})"
end

# Check user
user = User.find_by(email: "ebanocalderon@gmail.com")
if user
  user.password = "Mangudeplatano1!"
  user.password_confirmation = "Mangudeplatano1!"
  user.save!
  puts "Successfully reset password for existing user ebanocalderon@gmail.com"
else
  user = User.new(
    email: "ebanocalderon@gmail.com",
    password: "Mangudeplatano1!",
    password_confirmation: "Mangudeplatano1!",
    name: "Ebano Calderon",
    role: "administrator"
  )
  user.save!
  puts "Created user ebanocalderon@gmail.com."
end

# Link user to account if not already linked
unless AccountUser.exists?(account_id: account.id, user_id: user.id)
  AccountUser.create!(
    account: account,
    user: user,
    role: :administrator
  )
  puts "Linked user ebanocalderon@gmail.com to account #{account.name}."
else
  puts "User is already linked to the account."
end

# Set up SuperAdmin
super_admin = SuperAdmin.find_by(email: "ebanocalderon@gmail.com")
if super_admin
  super_admin.password = "Mangudeplatano1!"
  super_admin.password_confirmation = "Mangudeplatano1!"
  super_admin.save!
  puts "Successfully reset password for SuperAdmin ebanocalderon@gmail.com"
else
  SuperAdmin.create!(
    email: "ebanocalderon@gmail.com",
    password: "Mangudeplatano1!",
    password_confirmation: "Mangudeplatano1!"
  )
  puts "Created SuperAdmin ebanocalderon@gmail.com."
end

puts "--- Setup/Reset completed successfully! ---"
