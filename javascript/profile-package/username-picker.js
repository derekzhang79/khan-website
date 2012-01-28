/**
 * Code to handle the profile info changer.
 * TODO: rename away from username picker
 */

UsernamePickerView = Backbone.View.extend({
    id: "username-picker-container",

    events: {
        "keyup .username": "onUsernameKeyup_",
        "click #save-profile-info": "onSaveClick_",
        "click #cancel-profile-info": "toggle"
    },

    initialize: function() {
        this.template = Templates.get("profile.username-picker");
        this.shouldShowUsernameWarning_ = false;
        this.keyupTimeout = null;
        this.model.bind("validate:username",
            _.bind(this.showMessage_, this));
    },

    render: function() {
        // TODO: Make idempotent
        // maybe making the resetFields_ function obsolete
        var context = {
                username: this.model.get("username"),
                nickname: this.model.get("nickname")
            },
            html = this.template(context);

        $(this.el).html(html)
            .addClass("modal fade hide")
            .modal({
                keyboard: true,
                backdrop: true
            })
            .bind("hidden", _.bind(this.resetFields_, this))
            .bind("shown", _.bind(this.getUsernameWarningPromo_, this));
        return this;
    },

    toggle: function() {
        $(this.el).modal("toggle");
    },

    resetFields_: function() {
        var nickname = this.model.get("nickname"),
            username = this.model.get("username");

        this.$(".notification").hide();
        this.$(".nickname").val(nickname);
        this.$(".username").val(username);
        this.$(".example-username").val(username);
        this.$(".sidenote").text("").removeClass("success").removeClass("error");
        this.$("#save-profile-info").prop("disabled", false);
    },

    setShowUsernameWarning_: function(hasSeen) {
        this.shouldShowUsernameWarning_ = !hasSeen;
    },

    getUsernameWarningPromo_: function() {
        if(!this.model.get("username")) {
            return;
        }

        $.ajax({
            type: "GET",
            url: "/api/v1/user/username_promo",
            dataType: "json",
            success: _.bind(this.setShowUsernameWarning_, this)
        });
    },

    setUsernameWarningPromo_: function() {
        $.ajax({
            type: "POST",
            url: "/api/v1/user/username_promo"
        });
    },

    onUsernameKeyup_: function(e) {
        if (this.shouldShowUsernameWarning_) {
            $(".notification.error").show();
            this.setUsernameWarningPromo_();
            this.shouldShowUsernameWarning_ = false;
        }
        if (e.keyCode === 13) {
            // Pressing enter does not save. Should it?
            this.onTimeout_();
            return;
        }
        this.$(".example-username").text(this.$(".username").val());

        if (this.keyupTimeout) {
            clearTimeout(this.keyupTimeout);
        }
        this.keyupTimeout = setTimeout(_.bind(this.onTimeout_, this), 1000);
    },

    onTimeout_: function() {
        this.$(".sidenote").text("Checking username...")
            .removeClass("success")
            .removeClass("error");
        this.model.validateUsername(this.$(".username").val());
        this.keyupTimeout = null;
    },

    showMessage_: function(isValid, message) {
        if (isValid) {
            this.$(".sidenote").addClass("success").removeClass("error");
        } else {
            this.$(".sidenote").addClass("error").removeClass("success");
        }
        this.$("#save-profile-info").prop("disabled", !isValid);
        this.$(".sidenote").text(message);
    },

    onChangeSuccess_: function(model, response) {
        this.toggle();
    },

    onChangeError_: function(model, response) {
        this.showMessage_(false, response.responseText);
    },

    onSaveClick_: function() {
        var nickname = this.$(".nickname").val(),
            username = this.$(".username").val(),
            attrs = {
                nickname: nickname,
                username: username
            },
            options = {
                success: _.bind(this.onChangeSuccess_, this),
                error: _.bind(this.onChangeError_, this)
            };

        this.model.save(attrs, options);
    }
});
